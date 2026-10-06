"""Validate a batch before publication; retain per-file success/failure results."""
from pathlib import Path
from core.access import require_admin
from core import catalog

EXTENSIONS = {'.pdf', '.ppt', '.pptx', '.docx', '.mol2', '.cif'}


def validate_batch(files):
    if not 1 <= len(files) <= 50:
        raise ValueError('Select 1–50 documents per batch.')
    seen, normalized, total = set(), [], 0
    for filename, content in files:
        name = Path(filename.replace('\\', '/')).name
        if name.casefold() in seen:
            raise ValueError(f'Duplicate filename in batch: {name}. Rename it before uploading.')
        if Path(name).suffix.lower() not in EXTENSIONS or not content or len(content) > 20*1024*1024:
            raise ValueError(f'{name}: use a supported, non-empty file no larger than 20 MB.')
        seen.add(name.casefold())
        total += len(content)
        normalized.append((name, content))
    if total > 250*1024*1024:
        raise ValueError('The total batch must not exceed 250 MB.')
    return normalized


def submit_batch(files, principal, chunk_size=400, overlap=50, contains_personal=True):
    from core.pipeline import submit_uploaded_document
    from core.audit import record
    from phases.phase2_async.job_status import JobSubmissionError
    from core.versions import ExistingUpload
    require_admin(principal)
    normalized = validate_batch(files)
    results = []
    for name, content in normalized:
        try:
            # Stage privately. Publishing happens only after successful ingestion
            # and explicit review in Documents, never before a partial replacement.
            job_id = submit_uploaded_document(name, content, chunk_size, overlap,principal=principal)
            results.append({'filename': name, 'job_id': job_id, 'status': 'submitted', 'error': ''})
            record(principal, 'upload_submitted', {'document': name, 'job_id': job_id,
                                                  'contains_personal': contains_personal})
        except ExistingUpload as error:
            results.append({'filename':name,'job_id':error.job_id or '', 'status':'duplicate' if error.state=='success' else 'already_queued','error':str(error)})
        except JobSubmissionError as error:
            results.append({'filename':name,'job_id':error.job_id,'status':'uncertain',
                            'error':'Submission was not confirmed. Track this job ID before retrying; its staged file was retained.'})
        except Exception:
            results.append({'filename': name, 'job_id': '', 'status': 'failed',
                            'error': 'Could not confirm submission. Check the queue before retrying this file.'})
    return results
