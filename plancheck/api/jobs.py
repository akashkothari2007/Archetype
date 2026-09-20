"""Bounded, persisted local jobs with cooperative cancellation and progress history."""
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from typing import Any
from uuid import uuid4
from plancheck.core.schemas import JobStatus
from plancheck.core.settings import get_settings
from plancheck.services.repository import atomic_json
ProgressFn=Callable[...,None]
_lock=threading.RLock();_jobs={};_cancel={};_pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='archetype-job')
class JobCancelled(Exception):pass

def _path(jid):
    if not jid.isalnum():raise ValueError('Invalid job identifier')
    return get_settings().data_dir/'_jobs'/f'{jid}.json'

def get_job(job_id):
    with _lock:
        if job_id in _jobs:return _jobs[job_id].model_copy(deep=True)
        path=_path(job_id)
        if not path.exists():return None
        job=JobStatus.model_validate_json(path.read_text(encoding='utf8'))
        if job.state in ['running','queued']:
            job.state='error';job.phase='interrupted';job.error='The application restarted before this job finished.';job.message='Interrupted — run again to retry'
            atomic_json(path,job.model_dump())
        _jobs[job_id]=job
        return job.model_copy(deep=True)

_EVENT_EXTRA = ("kind", "detail", "sources", "rooms", "items", "label")

def _update(jid,**kw):
    extras={k:kw.pop(k) for k in _EVENT_EXTRA if k in kw}
    with _lock:
        current=_jobs[jid];kw={k:v for k,v in kw.items() if k in JobStatus.model_fields}
        current=current.model_copy(update=kw)
        if 'message' in kw or extras:
            event={'message':current.message,'phase':current.phase,'progress':current.progress,**extras}
            current.events=(current.events+[event])[-100:]
        _jobs[jid]=current;atomic_json(_path(jid),current.model_dump())

def cancel(job_id):
    job=get_job(job_id)
    if job is None:raise KeyError(job_id)
    if job.state in ['done','error','cancelled']:return job
    with _lock:_cancel.setdefault(job_id,threading.Event()).set()
    return job

def submit(fn:Callable[[ProgressFn],Any],message='Queued'):
    jid=uuid4().hex[:12]
    with _lock:_jobs[jid]=JobStatus(job_id=jid,state='queued',message=message);_cancel[jid]=threading.Event();atomic_json(_path(jid),_jobs[jid].model_dump())
    def report(**kw):
        if _cancel[jid].is_set():raise JobCancelled()
        _update(jid,**kw)
    def run():
        try:
            report(state='running',phase='working',message=message)
            result=fn(report)
            # fn performs a final cancellation check before any transactional commit.
            _update(jid,state='done',phase='completed',progress=1,result=result if isinstance(result,dict) else None)
        except JobCancelled:_update(jid,state='cancelled',phase='cancelled',message='Cancelled; committed project preserved')
        except Exception as exc:_update(jid,state='error',phase='failed',error=str(exc),message=str(exc))
    _pool.submit(run);return jid
