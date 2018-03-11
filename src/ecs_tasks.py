import sys, os
parent_dir = os.path.abspath(os.path.dirname(__file__))
vendor_dir = os.path.join(parent_dir, 'vendor')
sys.path.append(vendor_dir)

import time
import logging
import json
import boto3
import backoff
import datetime
from dateutil.tz import tzlocal,tzutc
from cfn_lambda_handler import Handler, CfnLambdaExecutionTimeout
from hashlib import md5
from lib import CfnManager
from lib import EcsTaskManager, EcsTaskFailureError, EcsTaskExitCodeError, EcsTaskTimeoutError
from lib import validate_cfn
from lib import cfn_error_handler

# Stack rollback states
ROLLBACK_STATES = ['ROLLBACK_IN_PROGRESS','UPDATE_ROLLBACK_IN_PROGRESS']

# Set handler as the entry point for Lambda
handler = Handler()

# Configure logging
logging.basicConfig()
log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# AWS services
task_mgr = EcsTaskManager()
cfn_mgr = CfnManager()
elb = boto3.client('elbv2')

# Starts an ECS task
def start(task):
  return task_mgr.start_task(
    cluster=task['Cluster'],
    taskDefinition=task['TaskDefinition'],
    overrides=task['Overrides'],
    count=task['Count'],
    containerInstances=task['Instances'],
    startedBy=task['StartedBy'],
    platformVersion=task['PlatformVersion'],
    launchType=task['LaunchType'],
    networkConfiguration=task['NetworkConfiguration']
  )

# Outputs JSON
def format_json(data):
  return json.dumps(data, default=lambda d: d.isoformat() if isinstance(d, datetime.datetime) else str(d))

# Transforms a list of dicts into a keyed dictionary
def to_dict(items, key, value):
  return dict(zip([i[key] for i in items], [i[value] for i in items]))

# Creates a fixed length consist ID based from a given stack ID and resource IC
def get_task_id(stack_id, resource_id):
  m = md5()
  m.update((stack_id + resource_id).encode('utf-8'))
  return m.hexdigest()

# Gets ECS task definition and returns environment variable values for a given set of update criteria
def get_task_definition_values(task_definition_arn, update_criteria):
  task_definition = task_mgr.describe_task_definition(task_definition_arn)
  containers = to_dict(task_definition['containerDefinitions'],'name','environment')
  return [env['value'] for u in update_criteria for env in containers.get(u['Container'],{}) if env['name'] in u['EnvironmentKeys']]

# Updates ECS task status
def describe_tasks(cluster, tasks):
  task_arns = [t.get('taskArn') for t in tasks]
  return task_mgr.describe_tasks(cluster=cluster, tasks=task_arns)

# Checks ECS task completion
def check_complete(task_result):
  if task_result.get('failures'):
    raise EcsTaskFailureError(task_result)
  tasks = task_result.get('tasks')
  return all(t.get('lastStatus') == 'STOPPED' for t in tasks)

# Checks ECS task exit codes
def check_exit_codes(task_result):
  tasks = task_result['tasks']
  non_zero = [c.get('taskArn') for t in tasks for c in t.get('containers') if c.get('exitCode') != 0]
  if non_zero:
    raise EcsTaskExitCodeError(tasks, non_zero)

# Polls an ECS task for completion 
@backoff.on_predicate(backoff.constant, lambda task: not check_complete(task['TaskResult']), interval=5)
def poll(task, remaining_time):
  if task['CreationTime'] + task['Timeout'] < int(time.time()):
    raise EcsTaskTimeoutError(task['TaskResult']['tasks'], task['CreationTime'], task['Timeout'])
  if remaining_time() <= 10000:
    raise CfnLambdaExecutionTimeout('poll(%s, context.get_remaining_time_in_millis)' % task)
  task['TaskResult'] = describe_tasks(task['Cluster'], task['TaskResult']['tasks'])
  return task

# Start and poll task
def start_and_poll(task, remaining_time):
  if task['TargetGroupHealthCheck']:
    check_target_health(task,remaining_time)
  task['TaskResult'] = start(task)
  if task['TaskResult'].get('failures'):
    raise EcsTaskFailureError(task['TaskResult'])
  log.info("Task created successfully with result: %s" % format_json(task['TaskResult']))
  if task['Timeout'] > 0:
    task = poll(task,remaining_time)
    check_exit_codes(task['TaskResult'])
    log.info("Task completed successfully with result: %s" % format_json(task['TaskResult']))
  return task

# Create task
def create_task(event):
  task = validate_cfn(event['ResourceProperties'])
  task['StartedBy'] = get_task_id(event['StackId'],event['LogicalResourceId'])
  event['Timeout'] = task['Timeout']
  task['CreationTime'] = event['CreationTime']
  log.info('Received task %s' % format_json(task))
  return task

# Performs a health check on the input target group
@backoff.on_predicate(backoff.constant, lambda x: not x, interval=5)
def check_target_health(task, remaining_time):
  target_group_arn = task['TargetGroupHealthCheck']
  if remaining_time() <= 10000:
    log.info("Function about to timeout, raising CfnLambdaExecutionTimeout to trigger reinvocation...")
    raise CfnLambdaExecutionTimeout('start_and_poll(%s, context.get_remaining_time_in_millis)' % task)
  else:
    log.info("Checking target health of target group %s", target_group_arn)
    result = elb.describe_target_health(TargetGroupArn=target_group_arn)
    return any(t for t in result['TargetHealthDescriptions'] if t['TargetHealth']['State'] == 'healthy')

# Event handlers
@handler.poll
@cfn_error_handler
def handle_poll(event, context):
  log.info('Received poll event %s' % str(event))
  task = eval(event.get('EventState'))
  check_exit_codes(task['TaskResult'])
  log.info("Task completed with result: %s" % task['TaskResult'])
  return {
    "Status": "SUCCESS", 
    "PhysicalResourceId": next(t['taskArn'] for t in task['TaskResult']['tasks'])
  }

@handler.create
@cfn_error_handler
def handle_create(event, context):
  log.info('Received create event %s' % str(event))
  task = create_task(event)
  if task['Count'] > 0:
    task = start_and_poll(task, context.get_remaining_time_in_millis)
    event['PhysicalResourceId'] = next(t['taskArn'] for t in task['TaskResult']['tasks'])
  return event

@handler.update
@cfn_error_handler
def handle_update(event, context):
  log.info('Received update event %s' % str(event))
  task = create_task(event)
  update_criteria = task['UpdateCriteria']
  should_run = task['RunOnUpdate'] and task['Count'] > 0
  if should_run:
    old_task = validate_cfn(event.get('OldResourceProperties'))
    if not task['RunOnRollback']:
      stack_status = cfn_mgr.get_stack_status(event['StackId'])
      should_run = stack_status not in ROLLBACK_STATES
    if update_criteria and should_run:
      old_values = get_task_definition_values(old_task['TaskDefinition'],update_criteria)
      new_values = get_task_definition_values(task['TaskDefinition'],update_criteria)
      should_run = old_values != new_values
  if should_run:
    task = start_and_poll(task, context.get_remaining_time_in_millis)
    event['PhysicalResourceId'] = next(t['taskArn'] for t in task['TaskResult']['tasks'])  
  return event
  
@handler.delete
@cfn_error_handler
def handle_delete(event, context):
  log.info('Received delete event %s' % str(event))
  task = create_task(event)
  tasks = task_mgr.list_tasks(cluster=task['Cluster'], startedBy=task['StartedBy'])
  for t in tasks:
    task_mgr.stop_task(cluster=task['Cluster'], task=t, reason='Delete requested for %s' % event['StackId'])
  return event