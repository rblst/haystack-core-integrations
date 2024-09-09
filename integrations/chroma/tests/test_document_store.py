# SPDX-FileCopyrightText: 2023-present John Doe <jd@example.com>
#
# SPDX-License-Identifier: Apache-2.0
import logging
import operator
import uuid
from typing import List
from unittest import mock

import numpy as np
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from haystack import Document
from haystack.testing.document_store import (
    CountDocumentsTest,
    DeleteDocumentsTest,
    LegacyFilterDocumentsTest,
)

from haystack_integrations.document_stores.chroma import ChromaDocumentStore


class _TestEmbeddingFunction(EmbeddingFunction):
    """
    Chroma lets you provide custom functions to compute embeddings,
    we use this feature to provide a fake algorithm returning random
    vectors in unit tests.
    """

    def __call__(self, input: Documents) -> Embeddings:  # noqa - chroma will inspect the signature, it must match
        # embed the documents somehow
        return [np.random.default_rng().uniform(-1, 1, 768).tolist()]


class TestDocumentStore(CountDocumentsTest, DeleteDocumentsTest, LegacyFilterDocumentsTest):
    """
    Common test cases will be provided by `DocumentStoreBaseTests` but
    you can add more to this class.
    """

    @pytest.fixture
    def document_store(self) -> ChromaDocumentStore:
        """
        This is the most basic requirement for the child class: provide
        an instance of this document store so the base class can use it.
        """
        with mock.patch(
            "haystack_integrations.document_stores.chroma.document_store.get_embedding_function"
        ) as get_func:
            get_func.return_value = _TestEmbeddingFunction()
            return ChromaDocumentStore(embedding_function="test_function", collection_name=str(uuid.uuid1()))

    def assert_documents_are_equal(self, received: List[Document], expected: List[Document]):
        """
        Assert that two lists of Documents are equal.
        This is used in every test, if a Document Store implementation has a different behaviour
        it should override this method.

        This can happen for example when the Document Store sets a score to returned Documents.
        Since we can't know what the score will be, we can't compare the Documents reliably.
        """
        received.sort(key=operator.attrgetter("id"))
        expected.sort(key=operator.attrgetter("id"))

        for doc_received, doc_expected in zip(received, expected):
            assert doc_received.content == doc_expected.content
            assert doc_received.meta == doc_expected.meta

    def test_ne_filter(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        """
        We customize this test because Chroma consider "not equal" true when
        a field is missing
        """
        document_store.write_documents(filterable_docs)
        result = document_store.filter_documents(filters={"page": {"$ne": "100"}})
        self.assert_documents_are_equal(
            result, [doc for doc in filterable_docs if doc.meta.get("page", "100") != "100"]
        )

    def test_delete_empty(self, document_store: ChromaDocumentStore):
        """
        Deleting a non-existing document should not raise with Chroma
        """
        document_store.delete_documents(["test"])

    def test_delete_not_empty_nonexisting(self, document_store: ChromaDocumentStore):
        """
        Deleting a non-existing document should not raise with Chroma
        """
        doc = Document(content="test doc")
        document_store.write_documents([doc])
        document_store.delete_documents(["non_existing"])

        assert document_store.filter_documents(filters={"id": doc.id}) == [doc]

    def test_search(self):
        document_store = ChromaDocumentStore()
        documents = [
            Document(content="First document", meta={"author": "Author1"}),
            Document(content="Second document"),  # No metadata
            Document(content="Third document", meta={"author": "Author2"}),
            Document(content="Fourth document"),  # No metadata
        ]
        document_store.write_documents(documents)
        result = document_store.search(["Third"], top_k=1)

        # Assertions to verify correctness
        assert len(result) == 1
        assert result[0][0].content == "Third document"

    def test_write_documents_unsupported_meta_values(self, document_store: ChromaDocumentStore):
        """
        Unsupported meta values should be removed from the documents before writing them to the database
        """

        docs = [
            Document(content="test doc 1", meta={"invalid": {"dict": "value"}}),
            Document(content="test doc 2", meta={"invalid": ["list", "value"]}),
            Document(content="test doc 3", meta={"ok": 123}),
        ]

        document_store.write_documents(docs)

        written_docs = document_store.filter_documents()
        written_docs.sort(key=lambda x: x.content)

        assert len(written_docs) == 3
        assert [doc.id for doc in written_docs] == [doc.id for doc in docs]
        assert written_docs[0].meta == {}
        assert written_docs[1].meta == {}
        assert written_docs[2].meta == {"ok": 123}

    @pytest.mark.integration
    def test_to_json(self, request):
        ds = ChromaDocumentStore(
            collection_name=request.node.name, embedding_function="HuggingFaceEmbeddingFunction", api_key="1234567890"
        )
        ds_dict = ds.to_dict()
        assert ds_dict == {
            "type": "haystack_integrations.document_stores.chroma.document_store.ChromaDocumentStore",
            "init_parameters": {
                "collection_name": "test_to_json",
                "embedding_function": "HuggingFaceEmbeddingFunction",
                "persist_path": None,
                "api_key": "1234567890",
                "distance_function": "l2",
            },
        }

    @pytest.mark.integration
    def test_from_json(self):
        collection_name = "test_collection"
        function_name = "HuggingFaceEmbeddingFunction"
        ds_dict = {
            "type": "haystack_integrations.document_stores.chroma.document_store.ChromaDocumentStore",
            "init_parameters": {
                "collection_name": "test_collection",
                "embedding_function": "HuggingFaceEmbeddingFunction",
                "persist_path": None,
                "api_key": "1234567890",
                "distance_function": "l2",
            },
        }

        ds = ChromaDocumentStore.from_dict(ds_dict)
        assert ds._collection_name == collection_name
        assert ds._embedding_function == function_name
        assert ds._embedding_function_params == {"api_key": "1234567890"}

    @pytest.mark.integration
    def test_same_collection_name_reinitialization(self):
        ChromaDocumentStore("test_1")
        ChromaDocumentStore("test_1")

    @pytest.mark.integration
    def test_distance_metric_initialization(self):
        store = ChromaDocumentStore("test_2", distance_function="cosine")
        assert store._collection.metadata["hnsw:space"] == "cosine"

        with pytest.raises(ValueError):
            ChromaDocumentStore("test_3", distance_function="jaccard")

    @pytest.mark.integration
    def test_distance_metric_reinitialization(self, caplog):
        store = ChromaDocumentStore("test_4", distance_function="cosine")

        with caplog.at_level(logging.WARNING):
            new_store = ChromaDocumentStore("test_4", distance_function="ip")

        assert (
            "Collection already exists. The `distance_function` and `metadata` parameters will be ignored."
            in caplog.text
        )
        assert store._collection.metadata["hnsw:space"] == "cosine"
        assert new_store._collection.metadata["hnsw:space"] == "cosine"

    @pytest.mark.integration
    def test_metadata_initialization(self, caplog):
        store = ChromaDocumentStore(
            "test_5",
            distance_function="cosine",
            metadata={
                "hnsw:space": "ip",
                "hnsw:search_ef": 101,
                "hnsw:construction_ef": 102,
                "hnsw:M": 103,
            },
        )
        assert store._collection.metadata["hnsw:space"] == "ip"
        assert store._collection.metadata["hnsw:search_ef"] == 101
        assert store._collection.metadata["hnsw:construction_ef"] == 102
        assert store._collection.metadata["hnsw:M"] == 103

        with caplog.at_level(logging.WARNING):
            new_store = ChromaDocumentStore(
                "test_5",
                metadata={
                    "hnsw:space": "l2",
                    "hnsw:search_ef": 101,
                    "hnsw:construction_ef": 102,
                    "hnsw:M": 103,
                },
            )

        assert (
            "Collection already exists. The `distance_function` and `metadata` parameters will be ignored."
            in caplog.text
        )
        assert store._collection.metadata["hnsw:space"] == "ip"
        assert new_store._collection.metadata["hnsw:space"] == "ip"

    # Override tests from LegacyFilterDocumentsTest
    def test_filter_nested_or_and(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        filters = {
            "$and": [
                {"page": {"$eq": "123"}},
                {"$or": [{"name": {"$in": ["name_0", "name_1"]}}, {"number": {"$lt": 1.0}}]},
            ]
        }

        document_store.write_documents(filterable_docs)
        result = document_store.filter_documents(filters)
        self.assert_documents_are_equal(
            result,
            [
                doc
                for doc in filterable_docs
                if (
                    doc.meta.get("page") in ["123"]
                    and (
                        doc.meta.get("name") in ["name_0", "name_1"]
                        or ("number" in doc.meta and doc.meta["number"] < 1)
                    )
                )
            ],
        )

    def test_filter_in_implicit(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        filters = {"page": {"$in": ["100", "123"]}}

        document_store.write_documents(filterable_docs)
        result = document_store.filter_documents(filters)
        self.assert_documents_are_equal(
            result,
            [doc for doc in filterable_docs if doc.meta.get("page") in ["123", "100"]],
        )

    def test_filter_nested_multiple_identical_operators_same_level(
        self, document_store: ChromaDocumentStore, filterable_docs: List[Document]
    ):

        document_store.write_documents(filterable_docs)
        filters = {
            "$or": [
                {
                    "$and": [
                        {"name": {"$in": ["name_0", "name_1"]}},
                        {"page": {"$eq": "100"}},
                    ]
                },
                {
                    "$and": [
                        {"chapter": {"$in": ["intro", "abstract"]}},
                        {"page": "123"},
                    ]
                },
            ]
        }
        result = document_store.filter_documents(filters=filters)
        self.assert_documents_are_equal(
            result,
            [
                doc
                for doc in filterable_docs
                if (
                    (doc.meta.get("name") in ["name_0", "name_1"] and doc.meta.get("page") == "100")
                    or (doc.meta.get("chapter") in ["intro", "abstract"] and doc.meta.get("page") == "123")
                )
            ],
        )

    def test_document_filter_contains(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        document_store.write_documents(filterable_docs)
        filters = {
            "$or": [
                {
                    "$and": [
                        {"name": {"$in": ["name_0", "name_1"]}},
                        {"page": {"$eq": "100"}},
                    ]
                },
                {"$contains": "FOO"},
            ]
        }
        result = document_store.filter_documents(filters=filters)
        self.assert_documents_are_equal(
            result,
            [
                doc
                for doc in filterable_docs
                if (
                    (doc.meta.get("name") in ["name_0", "name_1"] and doc.meta.get("page") == "100")
                    or doc.content
                    and "FOO" in doc.content
                )
            ],
        )

    def test_logical_and_document_filter_combination(
        self, document_store: ChromaDocumentStore, filterable_docs: List[Document]
    ):
        document_store.write_documents(filterable_docs)

        result = document_store.filter_documents(filters={"$contains": "FOO"})
        self.assert_documents_are_equal(
            result,
            [doc for doc in filterable_docs if doc.content and "FOO" in doc.content],
        )

    @pytest.mark.skip(reason="Filter on dataframe contents is not supported.")
    def test_filter_document_dataframe(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter on table contents is not supported.")
    def test_eq_filter_table(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter on embedding value is not supported.")
    def test_eq_filter_embedding(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="$in operator is not supported. Filter on table contents is not supported.")
    def test_in_filter_table(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="$in operator is not supported.")
    def test_in_filter_embedding(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter on table contents is not supported.")
    def test_ne_filter_table(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter on embedding value is not supported.")
    def test_ne_filter_embedding(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="$nin operator is not supported. Filter on table contents is not supported.")
    def test_nin_filter_table(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="$nin operator is not supported. Filter on embedding value is not supported.")
    def test_nin_filter_embedding(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="$nin operator is not supported.")
    def test_nin_filter(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_simple_implicit_and_with_multi_key_dict(
        self, document_store: ChromaDocumentStore, filterable_docs: List[Document]
    ):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_simple_explicit_and_with_list(
        self, document_store: ChromaDocumentStore, filterable_docs: List[Document]
    ):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_simple_implicit_and(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_nested_implicit_and(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_simple_or(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_nested_or(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter on table contents is not supported.")
    def test_filter_nested_and_or_explicit(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass

    @pytest.mark.skip(reason="Filter syntax not supported.")
    def test_filter_nested_and_or_implicit(self, document_store: ChromaDocumentStore, filterable_docs: List[Document]):
        pass
