"""Temporary chat interpretation. Real model tools run outside this provider."""
import re
from plancheck.services.repairs import propose_repairs

def respond(building,rules,message,context='2D',selected_ids=None,report=None):
    text=message.lower().strip();selected_ids=selected_ids or []
    if any(word in text for word in ['fix','repair','resolve','check','issues','compliance']):
        proposal=propose_repairs(building,rules,report)
        count=proposal['summary']['proposed'];blocked=proposal['summary']['blocked']
        return {**proposal,'message':f'I checked the approved requirements and prepared {count} verifiable repair'+('s' if count!=1 else '')+f'. {blocked} issue'+('s remain' if blocked!=1 else ' remains')+' blocked. Review the changes before applying them.','actor':'agent'}
    materials={'white':'plaster','oak':'oak','tile':'tile','concrete':'concrete','sage':'sage','terracotta':'terracotta'}
    material=next((value for word,value in materials.items() if word in text),None)
    if material and selected_ids:
        commands=[{'kind':'set_material','target_id':eid,'params':{'material':material}} for eid in selected_ids]
        return {'commands':commands,'tasks':[],'blocked':[],'message':f'I prepared a {material} finish for your selection. Apply to update the model.','actor':'user','summary':{'proposed':len(commands),'blocked':0}}
    if 'sun' in text or 'evening' in text or 'morning' in text:
        time=18 if 'evening' in text else 8 if 'morning' in text else 14
        return {'commands':[{'kind':'set_environment','params':{'time':time}}],'tasks':[],'blocked':[],'message':f'I prepared lighting for {time:02d}:00.','actor':'user','summary':{'proposed':1,'blocked':0}}
    return {'commands':[],'tasks':[],'blocked':[],'message':'I can check approved requirements and prepare repairs, change a selected wall or floor to oak, tile, concrete, sage or white, and set morning or evening lighting. Select geometry, then describe one of these changes. This temporary provider does not interpret unrestricted design requests.','actor':'agent','summary':{'proposed':0,'blocked':0}}
