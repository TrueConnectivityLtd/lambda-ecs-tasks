import pytest
import time
from copy import deepcopy
import mock
import datetime
from dateutil.tz import tzutc
from uuid import uuid4
from lib import EcsTaskManager, CfnManager
from .constants import *

# Patched create_task module
@pytest.fixture()
def create_task():
  with mock.patch('boto3.client') as client:
    import create_task
    client.run_task.return_value = START_TASK_RESULT
    task_mgr = EcsTaskManager()
    task_mgr.client = client
    create_task.task_mgr = task_mgr
    yield create_task

# Patched check_task module
@pytest.fixture()
def check_task():
  with mock.patch('boto3.client') as client:
    import check_task
    client.describe_tasks.return_value = RUNNING_TASK_RESULT
    task_mgr = EcsTaskManager()
    task_mgr.client = client
    check_task.task_mgr = task_mgr
    yield check_task

@pytest.fixture
def create_task_event():
  return {
    'Cluster': CLUSTER_NAME,
    'TaskDefinition': OLD_TASK_DEFINITION_ARN,
    'Count': 1
  }

@pytest.fixture
def check_task_event():
  return {
    'Cluster': CLUSTER_NAME,
    'TaskDefinition': OLD_TASK_DEFINITION_ARN,
    'Count': 1,
    'Status': 'PENDING',
    'Tasks': START_TASK_RESULT['tasks'],
    'Failures': [],
    'CreateTimestamp': UTC.isoformat() + 'Z',
    'Timeout': 60
  }

# Lambda context mock
@pytest.fixture
def context():
  context = mock.Mock()
  context.aws_request_id = REQUEST_ID
  context.invoked_function_arn = FUNCTION_ARN
  context.client_context = None
  context.identity = None
  context.function_name = FUNCTION_NAME
  context.function_version = '$LATEST'
  context.memory_limit_in_mb = MEMORY_LIMIT
  context.get_remaining_time_in_millis.return_value = 300000
  yield context

# Mocked time.sleep function
@pytest.fixture
def time():
  with mock.patch('time.sleep', return_value=None) as time:
    yield time

# Mocked time.time function
@pytest.fixture
def now(time):
  with mock.patch('time.time', return_value=NOW) as now:
    yield now

# Patched ECS task manager
@pytest.fixture
def task_mgr():
  with mock.patch('boto3.client') as client:
    client.run_task.return_value = START_TASK_RESULT
    client.describe_tasks.return_value = STOPPED_TASK_RESULT
    client.describe_task_definition.side_effect = lambda taskDefinition: TASK_DEFINITION_RESULTS[taskDefinition]
    task_mgr = EcsTaskManager()
    task_mgr.client = client
    yield task_mgr

# Patched CFN manager
@pytest.fixture
def cfn_mgr():
  with mock.patch('boto3.client') as client:
    cfn_mgr = CfnManager()
    client.describe_stacks.side_effect = lambda StackName: DESCRIBE_STACKS_RESULT
    cfn_mgr.client = client
    yield cfn_mgr

# Patched ELB client
@pytest.fixture
def elb_client():
  with mock.patch('boto3.client') as client:
    client.describe_target_health.side_effect = [TARGET_HEALTH_INITIAL,TARGET_HEALTH_HEALTHY]
    yield client

# Patched task manager
@pytest.fixture
def ecs_client():
  with mock.patch('boto3.client') as client:
    client.run_task.return_value = START_TASK_RESULT
    client.describe_tasks.return_value = STOPPED_TASK_RESULT
    client.describe_task_definition.side_effect = lambda taskDefinition: TASK_DEFINITION_RESULTS[taskDefinition]
    client.list_tasks.side_effect = [LIST_TASKS_RESULT]
    client.stop_task.side_effect = [STOPPED_TASK_RESULT]
    yield client

# Patched ecs_tasks module
@pytest.fixture
def ecs_tasks(elb_client, ecs_client):
  import ecs_tasks
  task_mgr = EcsTaskManager()
  task_mgr.client = ecs_client
  ecs_tasks.task_mgr = task_mgr
  ecs_tasks.elb = elb_client
  yield ecs_tasks

# CFN Create Request
@pytest.fixture
def create_event():
  import ecs_tasks
  event = {
    'StackId': STACK_ID,
    'ResponseURL': 'https://cloudformation-custom-resource-response-uswest2.s3-us-west-2.amazonaws.com/arn%3Aaws%3Acloudformation%3Aus-west-2%3A429614120872%3Astack/intake-accelerator-dev/12947b30-d31a-11e6-93df-503acbd4dc61%7CMyLogGroup%7C720958cb-c5b7-4225-b12f-e7c5ab6c499b?AWSAccessKeyId=AKIAI4KYMPPRGIACET5Q&Expires=1483789136&Signature=GoZZ7Leg5xRsKq1hjU%2FO81oeJmw%3D',
    'ResourceProperties': {
      'ServiceToken': FUNCTION_ARN,
      'Cluster': CLUSTER_NAME,
      'TaskDefinition': OLD_TASK_DEFINITION_ARN
    },
    'ResourceType': RESOURCE_TYPE,
    'RequestType': 'Create',
    'CreationTime': NOW,
    'ServiceToken': FUNCTION_ARN,
    'RequestId': REQUEST_ID,
    'LogicalResourceId': LOGICAL_RESOURCE_ID,
    'Status': 'SUCCESS',
    'PhysicalResourceId': ecs_tasks.get_task_id(STACK_ID,LOGICAL_RESOURCE_ID)
  }
  yield event

# CFN Update Request
@pytest.fixture
def update_event():
  event = next(create_event())
  event['RequestType'] = 'Update'
  event['PhysicalResourceId'] = PHYSICAL_RESOURCE_ID
  event['OldResourceProperties'] = {
    'Destroy': 'false', 
    'ServiceToken': FUNCTION_ARN,
    'Cluster': CLUSTER_NAME,
    'TaskDefinition': OLD_TASK_DEFINITION_ARN
  }
  yield event

# CFN Delete Request
@pytest.fixture
def delete_event():
  event = next(create_event())
  event['RequestType'] = 'Delete'
  event['PhysicalResourceId'] = PHYSICAL_RESOURCE_ID
  yield event

# Generates each handler with corresponding event
@pytest.fixture(
  ids=['Create','Update','Delete'],
  params=[
    ('handle_create',create_event),
    ('handle_update',update_event),
    ('handle_delete',delete_event)
  ]
)
def handlers(request):
  yield(request.param[0],next(request.param[1]()))

# Generates Create and Update handlers with corresponding event
@pytest.fixture(
  ids=['Create','Update'],
  params=[
    ('handle_create',create_event),
    ('handle_update',update_event)
  ]
)
def create_update_handlers(request):
  yield(request.param[0],next(request.param[1]()))

# Check validation of required properties
@pytest.fixture(params = ['Cluster','TaskDefinition'])
def required_property(request):
  yield request.param
  
# Check validation of illegal property values
@pytest.fixture(
  ids = [
    'Count','RunOnUpdate','RunOnRollback','Timeout','PollInterval','Instances','Overrides'
  ], 
  params=[
    ('Count','50'),               # Maximum count = 10
    ('RunOnUpdate','never'),      # RunOnUpdate is a boolean
    ('RunOnRollback', 'always'),  # RunOnRollback is a boolean
    ('Timeout','4000'),           # Maximum timeout = 3600
    ('PollInterval','300'),       # Maximum poll interval = 60
    ('Instances',range(0,11)),    # Maximum number of instances = 10
    ('Overrides',[])              # Overrides is of type dict
  ])
def invalid_property(request):
  yield request.param