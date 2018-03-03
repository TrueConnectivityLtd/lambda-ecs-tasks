from functools import partial
from .utils import paginated_response
import boto3

class EcsTaskFailureError(Exception):
    def __init__(self, task):
        self.task = task
        self.taskArn = next((t['taskArn'] for t in task.get('tasks')),None)
        self.failures = task.get('failures')

class EcsTaskExitCodeError(Exception):
    def __init__(self, task, non_zero):
        self.task = task
        self.taskArn = next((t['taskArn'] for t in task),None)
        self.non_zero = non_zero

class EcsTaskTimeoutError(Exception):
    def __init__(self, tasks, creation, timeout):
        self.creation = creation
        self.timeout = timeout
        self.tasks = tasks
        self.taskArn = next((t['taskArn'] for t in tasks),None)

class EcsTaskManager:
  """Handles ECS Tasks"""
  def __init__(self):
    self.client = boto3.client('ecs')

  def get_container_instances(self, cluster, instance_ids):
    containers = self.client.list_container_instances(cluster).get('containerInstanceArns')
    describe_containers = self.client.describe_container_instances(cluster=cluster, containerInstances=containers).get('containerInstances')
    return [c.get('containerInstanceArn') for c in describe_containers if c.get('ec2InstanceId') in instance_ids]
    
  def list_container_instances(self, cluster):
    func = partial(self.client.list_container_instances,cluster=cluster)
    return paginated_response(func, 'containerInstanceArns')

  def start_task(self, **kwargs):
    if kwargs.get('containerInstances') and kwargs.get('launchType') != 'EC2':
      raise ValueError("You must specify a launch type of EC2 when specifying container instances")
    if kwargs.get('containerInstances'):
      kwargs.pop('launchType',None)
      kwargs.pop('platformVersion',None)
      return self.client.start_task(**kwargs)
    else:
      kwargs.pop('containerInstances',None)
      return self.client.run_task(**kwargs)

  def describe_tasks(self, cluster, tasks):
    return self.client.describe_tasks(cluster=cluster, tasks=tasks)

  def describe_task_definition(self, task_definition):
    response = self.client.describe_task_definition(taskDefinition=task_definition)
    return response['taskDefinition']

  def list_tasks(self, cluster, **kwargs):
    func = partial(self.client.list_tasks,cluster=cluster,**kwargs)
    return paginated_response(func, 'taskArns')

  def stop_task(self, cluster, task, reason='unknown'):
    return self.client.stop_task(cluster=cluster, task=task, reason=reason)

  # Checks ECS task completion
  def check_status(self, tasks):
    stats = [t.get('lastStatus') for t in tasks]
    if 'PENDING' in stats:
      status = 'PENDING'
    elif 'RUNNING' in stats:
      status = 'RUNNING'
    else:
      status = 'STOPPED'
    return status