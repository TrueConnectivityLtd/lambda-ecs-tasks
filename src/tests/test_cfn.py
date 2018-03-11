import pytest
from .constants import *
from cfn_lambda_handler import CfnLambdaExecutionTimeout

# Test poll request completes successfully
def test_poll_task_completes(ecs_tasks, create_event, context, time):
  # The 10000 value will trigger a CfnLambdaExecutionTimeout event
  context.get_remaining_time_in_millis.side_effect = [20000,10000,20000,20000]
  # The ECS task will be running on first poll and will complete on second poll
  ecs_tasks.task_mgr.client.describe_tasks.side_effect = [RUNNING_TASK_RESULT,STOPPED_TASK_RESULT]
  # Simulated create event
  with pytest.raises(CfnLambdaExecutionTimeout) as e:
    response = ecs_tasks.handle_create(create_event, context)
  # Simulated poll event
  poll_event = create_event
  poll_event['EventState'] = e.value.state  
  assert poll_event['EventState']['TaskResult'] == RUNNING_TASK_RESULT
  # Process the poll request during which the task will complete
  response = ecs_tasks.handle_poll(poll_event, context)
  assert ecs_tasks.task_mgr.client.run_task.call_count == 1
  assert ecs_tasks.task_mgr.client.describe_tasks.call_count == 2
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test poll request fails after maximum timeout 
def test_poll_task_timeout(ecs_tasks, create_event, context, time, now):
  create_event['ResourceProperties']['Timeout'] = 3600
  context.get_remaining_time_in_millis.side_effect = [20000,10000]
  ecs_tasks.task_mgr.client.describe_tasks.side_effect = lambda cluster,tasks: RUNNING_TASK_RESULT
  # Simulated create event
  with pytest.raises(CfnLambdaExecutionTimeout) as e:
    response = ecs_tasks.handle_create(create_event, context)
  # Run a polling loop
  poll_event = create_event
  poll_event['EventState'] = e.value.state
  completed = False
  while not completed:
    # Fast forward 60 seconds
    now.return_value += 60
    # Let the handler check task status once and then run out of execution time
    context.get_remaining_time_in_millis.side_effect = [20000,10000]
    try:
      # Process the poll request - the task will never complete
      response = ecs_tasks.handle_poll(poll_event, context)
    except CfnLambdaExecutionTimeout as execution_timeout:
      poll_event['EventState'] = execution_timeout.state
    else:
      # At this point the request has hit absolute timeout and completed
      completed = True
  assert ecs_tasks.task_mgr.client.run_task.call_count == 1
  assert ecs_tasks.task_mgr.client.describe_tasks.call_count == 61
  assert response['Status'] == 'FAILED'
  assert 'The task failed to complete with the specified timeout of 3600 seconds' in response['Reason']

# Test delete request when task is already stopped 
def test_delete_task_stopped(ecs_tasks, delete_event, context, time):
  ecs_tasks.task_mgr.client.list_tasks.side_effect = [{'taskArns':[]}]
  response = ecs_tasks.handle_delete(delete_event, context)
  assert not ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert ecs_tasks.task_mgr.client.list_tasks.called
  assert not ecs_tasks.task_mgr.client.stop_task.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test running task is stopped on delete
def test_running_task_is_stopped_on_delete(ecs_tasks, delete_event, context, time):
  response = ecs_tasks.handle_delete(delete_event, context)
  assert not ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert ecs_tasks.task_mgr.client.list_tasks.called
  assert ecs_tasks.task_mgr.client.stop_task.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test task is not run on stack rollback when RunOnRollback is false
def test_no_run_when_run_on_rollback_disabled(ecs_tasks, cfn_mgr, update_event, context, time):
  ecs_tasks.cfn_mgr = cfn_mgr
  update_event['ResourceProperties']['RunOnRollback'] = 'False'
  response = ecs_tasks.handle_update(update_event, context)
  assert cfn_mgr.client.describe_stacks.called
  assert not ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test task is run when UpdateCriteria is met
def test_run_when_update_criteria_met(ecs_tasks, cfn_mgr, update_event, context, time):
  ecs_tasks.cfn_mgr = cfn_mgr
  update_event['ResourceProperties']['UpdateCriteria'] = UPDATE_CRITERIA
  update_event['ResourceProperties']['TaskDefinition'] = NEW_TASK_DEFINITION_ARN
  response = ecs_tasks.handle_update(update_event, context)
  assert ecs_tasks.task_mgr.client.describe_task_definition.called
  assert ecs_tasks.task_mgr.client.run_task.called
  assert ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test task is not run when UpdateCriteria is not met
def test_no_run_when_update_criteria_not_met(ecs_tasks, cfn_mgr, update_event, context, time):
  ecs_tasks.cfn_mgr = cfn_mgr
  update_event['ResourceProperties']['UpdateCriteria'] = UPDATE_CRITERIA
  response = ecs_tasks.handle_update(update_event, context)
  assert ecs_tasks.task_mgr.client.describe_task_definition.called
  assert not ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test task is not run when RunOnUpdate is false
def test_no_run_when_run_on_update_disabled(ecs_tasks, update_event, context, time):
  update_event['ResourceProperties']['RunOnUpdate'] = 'False'
  response = ecs_tasks.handle_update(update_event, context)
  assert not ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Run task
def test_run_task(ecs_tasks, create_update_handlers, context, time):
  handler = getattr(ecs_tasks, create_update_handlers[0])
  event = create_update_handlers[1]
  response = handler(event, context)
  assert ecs_tasks.task_mgr.client.run_task.called
  assert ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Run asychronous task (returns immediately without polling)
def test_run_task_zero_timeout(ecs_tasks, create_update_handlers, context, time):
  handler = getattr(ecs_tasks, create_update_handlers[0])
  event = create_update_handlers[1]
  event['ResourceProperties']['Timeout'] = 0
  response = handler(event, context)
  assert ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert not time.sleep.called
  assert response['Status'] == 'SUCCESS'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID

# Test for ECS task failure
def test_run_task_failure(ecs_tasks, create_update_handlers, context, time):
  ecs_tasks.task_mgr.client.run_task.return_value = TASK_FAILURE
  handler = getattr(ecs_tasks, create_update_handlers[0])
  event = create_update_handlers[1]
  response = handler(event, context)
  assert ecs_tasks.task_mgr.client.run_task.called
  assert response['Status'] == 'FAILED'
  assert 'A task failure occurred' in response['Reason']

# Test for ECS task with non-zero containers
def test_run_task_non_zero_exit_code(ecs_tasks, create_update_handlers, context, time):
  ecs_tasks.task_mgr.client.describe_tasks.return_value = FAILED_TASK_RESULT
  handler = getattr(ecs_tasks, create_update_handlers[0])
  event = create_update_handlers[1]
  response = handler(event, context)
  assert ecs_tasks.task_mgr.client.run_task.called
  assert ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'FAILED'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID
  assert 'One or more containers failed with a non-zero exit code' in response['Reason']

# Test for ECS task that does not complete within Lambda execution timeout
def test_run_task_execution_timeout(ecs_tasks, create_update_handlers, context, time):
  context.get_remaining_time_in_millis.return_value = 1000
  handler = getattr(ecs_tasks, create_update_handlers[0])
  event = create_update_handlers[1]
  with pytest.raises(CfnLambdaExecutionTimeout) as e:
    response = handler(event, context)
    assert ecs_tasks.task_mgr.client.run_task.called
    assert not ecs_tasks.task_mgr.client.describe_tasks.called
    assert e.value.state['TaskResult'] == START_TASK_RESULT

# Test for ECS task that does not complete within absolute task timeout
def test_create_new_task_completion_timeout(ecs_tasks, create_update_handlers, context, time, now):
  # Now returns time in the future past the timeout
  now.return_value += 120
  handler = getattr(ecs_tasks, create_update_handlers[0])
  event = create_update_handlers[1]
  event['ResourceProperties']['Timeout'] = 60
  response = handler(event, context)
  assert ecs_tasks.task_mgr.client.run_task.called
  assert not ecs_tasks.task_mgr.client.describe_tasks.called
  assert response['Status'] == 'FAILED'
  assert response['PhysicalResourceId'] == PHYSICAL_RESOURCE_ID
  assert 'The task failed to complete with the specified timeout of 60 seconds' in response['Reason']

# Test for missing required properties in custom resource 
def test_missing_property(ecs_tasks, handlers, required_property, context, time):
  handler = getattr(ecs_tasks, handlers[0])
  event = handlers[1]
  del event['ResourceProperties'][required_property]
  response = ecs_tasks.handle_create(event,context)
  assert response['Status'] == 'FAILED'
  assert 'One or more invalid event properties' in response['Reason']
  assert ecs_tasks.task_mgr.client.run_task.was_not_called
  assert ecs_tasks.task_mgr.client.describe_tasks.was_not_called

# Test for invalid properties in custom resource 
def test_invalid_property(ecs_tasks, handlers, invalid_property, context, time):
  handler = getattr(ecs_tasks, handlers[0])
  event = handlers[1]
  event['ResourceProperties'][invalid_property[0]] = invalid_property[1]
  response = handler(event,context)
  assert response['Status'] == 'FAILED'
  assert 'One or more invalid event properties' in response['Reason']
  assert ecs_tasks.task_mgr.client.run_task.was_not_called
  assert ecs_tasks.task_mgr.client.describe_tasks.was_not_called
