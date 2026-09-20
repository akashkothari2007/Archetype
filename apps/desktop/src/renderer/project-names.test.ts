import {describe,expect,it} from 'vitest';
import {normalizeProjectName,projectNameKey,uniqueProjectName} from './project-names';

const projects=[
  {project_id:'a',name:'Willow House'},
  {project_id:'b',name:'North Annex'},
  {project_id:'c',name:'Willow House (2)'},
];

describe('project names',()=>{
  it('collapses whitespace and compares names without case',()=>{
    expect(normalizeProjectName('  Willow   House ')).toBe('Willow House');
    expect(projectNameKey('WILLOW HOUSE')).toBe('willow house');
  });

  it('keeps a free name and numbers copies',()=>{
    expect(uniqueProjectName(projects,'North Annex','b')).toBe('North Annex');
    expect(uniqueProjectName(projects,'Willow House')).toBe('Willow House (3)');
    expect(uniqueProjectName(projects,'willow house')).toBe('willow house (3)');
    expect(uniqueProjectName(projects,'Willow House (2)')).toBe('Willow House (3)');
    expect(uniqueProjectName(projects,'  ')).toBe('');
  });
});
