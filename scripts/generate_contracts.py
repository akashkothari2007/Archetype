"""Generate the desktop contract from the backend's authoritative Pydantic types."""
import json
from pathlib import Path
from pydantic import BaseModel
from plancheck.core.building import Building,DesktopProject,ModelCommand
class Contracts(BaseModel):
    building:Building
    project:DesktopProject
    command:ModelCommand
path=Path(__file__).resolve().parents[1]/'packages/contracts/schema.json'
schema=Contracts.model_json_schema()
for definition in schema.get('$defs',{}).values():
    if definition.get('title') != 'ModelCommand' and 'properties' in definition:
        definition['required']=list(definition['properties'])
def compatible(value):
    if isinstance(value,dict):
        if 'prefixItems' in value: value['items']=value.pop('prefixItems')
        for child in value.values(): compatible(child)
    elif isinstance(value,list):
        for child in value: compatible(child)
compatible(schema)
path.write_text(json.dumps(schema,indent=2)+'\n')
