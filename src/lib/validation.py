from voluptuous import Required, All, Any, Range, Schema, Length, Coerce, Boolean

# For Overrides, which must specify all values as strings
def DictToString(value):
  def string_values(node):
    if type(node) is dict:
      result={}
      for k,v in node.items():
        result[k] = string_values(v)
    elif type(node) is list:
      result=[]
      for v in node:
        result.append(string_values(v))
    else:
      result = str(node)
    return result
  if isinstance(value, dict):
    return string_values(value)
  else:
    raise ValueError

# Validation Helper
def get_cfn_validator():
  return Schema({
  Required('Cluster'): All(str),
  Required('TaskDefinition'): All(str),
  Required('Count', default=1): All(Coerce(int), Range(min=0, max=10)),
  Required('RunOnUpdate', default=True): All(Boolean()),
  Required('UpdateCriteria', default=[]): All([Schema({
    Required('Container'): All(str),
    Required('EnvironmentKeys'): All(list)
  })]),
  Required('RunOnRollback', default=True): All(Boolean()),
  Required('Timeout', default=290): All(Coerce(int), Range(min=0, max=3600)),
  Required('PollInterval', default=10): All(Coerce(int), Range(min=10, max=60)),
  Required('Overrides', default=dict()): All(DictToString),
  Required('Instances', default=list()): All(list, Length(max=10)),
}, extra=True)

# Validation Helper
def get_ecs_validator():
  return Schema({
  Required('Cluster'): All(str),
  Required('TaskDefinition'): All(str),
  Required('Count', default=1): All(Coerce(int), Range(min=1, max=10)),
  Required('Overrides', default=dict()): All(DictToString),
  Required('Instances', default=list()): All(list, Length(max=10)),
  Required('Tasks', default=list()): All(list),
  Required('Status', default=''): All(str),
  Required('StartedBy', default='admin'): All(str),
  Required('Timeout', default=3600): All(Coerce(int), Range(min=60, max=604800)),
  Required('Poll', default=10): All(Coerce(int), Range(min=10, max=3600))
}, extra=True)

# Validation Helper
def validate_ecs(data):
  request_validator = get_ecs_validator()
  return request_validator(data)

# Validation Helper
def validate_cfn(data):
  request_validator = get_cfn_validator()
  return request_validator(data)