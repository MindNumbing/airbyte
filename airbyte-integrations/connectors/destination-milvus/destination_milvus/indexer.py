#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#


from typing import List, Optional

from airbyte_cdk.destinations.vector_db_based.document_processor import METADATA_RECORD_ID_FIELD, METADATA_STREAM_FIELD, Chunk
from airbyte_cdk.destinations.vector_db_based.embedder import Embedder
from airbyte_cdk.destinations.vector_db_based.indexer import Indexer
from airbyte_cdk.destinations.vector_db_based.utils import format_exception
from airbyte_cdk.models import ConfiguredAirbyteCatalog
from airbyte_cdk.models.airbyte_protocol import DestinationSyncMode
from destination_milvus.config import MilvusIndexingConfigModel
from pymilvus import Collection, DataType, connections
from pymilvus.exceptions import DescribeCollectionException


class MilvusIndexer(Indexer):
    config: MilvusIndexingConfigModel

    def __init__(self, config: MilvusIndexingConfigModel, embedder: Embedder):
        super().__init__(config, embedder)

    def _create_client(self):
        connections.connect(
            uri=self.config.host,
            db_name=self.config.db if self.config.db else "",
            user=self.config.auth.username if self.config.auth.mode == "username_password" else "",
            password=self.config.auth.password if self.config.auth.mode == "username_password" else "",
            token=self.config.auth.token if self.config.auth.mode == "token" else "",
        )
        self._collection = Collection(self.config.collection)

    def check(self) -> Optional[str]:
        try:
            self._create_client()

            description = self._collection.describe()
            if not description["auto_id"]:
                return "Only collections with auto_id are supported"
            vector_field = next((field for field in description["fields"] if field["name"] == self.config.vector_field), None)
            if vector_field is None:
                return f"Vector field {self.config.vector_field} not found"
            if vector_field["type"] != DataType.FLOAT_VECTOR:
                return f"Vector field {self.config.vector_field} is not a vector"
            if vector_field["params"]["dim"] != self.embedder.embedding_dimensions:
                return f"Vector field {self.config.vector_field} is not a {self.embedder.embedding_dimensions}-dimensional vector"
        except DescribeCollectionException:
            return f"Collection {self.config.collection} does not exist"
        except Exception as e:
            return format_exception(e)
        return None

    def pre_sync(self, catalog: ConfiguredAirbyteCatalog) -> None:
        self._create_client()
        for stream in catalog.streams:
            if stream.destination_sync_mode == DestinationSyncMode.overwrite:
                self._delete_for_filter(f'{METADATA_STREAM_FIELD} == "{stream.stream.name}"')

    def _delete_for_filter(self, expr: str) -> None:
        iterator = self._collection.query_iterator(expr=expr)
        page = iterator.next()
        while len(page) > 0:
            id_field = next(iter(page[0].keys()))
            ids = [next(iter(entity.values())) for entity in page]
            id_list_expr = ", ".join([str(id) for id in ids])
            self._collection.delete(expr=f"{id_field} in [{id_list_expr}]")
            page = iterator.next()

    def index(self, document_chunks: List[Chunk], delete_ids: List[str]) -> None:
        if len(delete_ids) > 0:
            id_list_expr = ", ".join([f'"{id}"' for id in delete_ids])
            id_expr = f"{METADATA_RECORD_ID_FIELD} in [{id_list_expr}]"
            self._delete_for_filter(id_expr)
        embedding_vectors = self.embedder.embed_texts([chunk.page_content for chunk in document_chunks])
        entities = []
        for i in range(len(document_chunks)):
            chunk = document_chunks[i]
            entities.append({**chunk.metadata, self.config.vector_field: embedding_vectors[i], self.config.text_field: chunk.page_content})
        self._collection.insert(entities)
