from celery import shared_task

from .services import process_document


@shared_task
def process_document_task(document_id):
    return process_document(document_id)
