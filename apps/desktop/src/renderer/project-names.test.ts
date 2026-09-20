import {describe,expect,it} from 'vitest';
import {duplicateNameIds,findNameConflict,normalizeProjectName,projectNameKey} from './project-names';

const projects=[
  {project_id:'a',name:'Willow House'},
  {project_id:'b',name:'North Annex'},
  {project_id:'c',name:'willow  house'},
];

describe('project names',()=>{
  it('collapses whitespace and compares names without case',()=>{
    expect(normalizeProjectName('  Willow   House ')).toBe('Willow House');
    expect(projectNameKey('WILLOW HOUSE')).toBe('willow house');
  });

  it('finds another project with the same name',()=>{
    expect(findNameConflict(projects,'willow house','c')?.project_id).toBe('a');
    expect(findNameConflict(projects,'North Annex','b')).toBeNull();
    expect(findNameConflict(projects,'  ')).toBeNull();
  });

  it('marks every project that shares a name',()=>{
    expect([...duplicateNameIds(projects)].sort()).toEqual(['a','c']);
  });
});
