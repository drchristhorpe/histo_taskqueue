"""Shared pytest fixtures: an isolated app + queue backed by a temp dir."""

from __future__ import annotations

import pytest

from histo_taskqueue.app import create_app
from histo_taskqueue.config import Config
from histo_taskqueue.index import JobIndex
from histo_taskqueue.queue import JobQueue
from histo_taskqueue.store import LocalFileStore


@pytest.fixture
def config(tmp_path) -> Config:
    # Point the allele registry at a non-existent path so the ~9,700-entry
    # bundled registry is not parsed for every test app (keeps the suite fast).
    return Config(
        store_backend="local",
        data_dir=tmp_path,
        alleles_path=tmp_path / "no_alleles",
    )


@pytest.fixture
def queue(config) -> JobQueue:
    store = LocalFileStore(config.resolved_objects_dir())
    index = JobIndex(config.resolved_index_path())
    return JobQueue(store, index)


@pytest.fixture
def app(config):
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


# A tiny valid haemoglobin-ish fragment for tests.
SEQ_A = "MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHF"
SEQ_B = "MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLST"
