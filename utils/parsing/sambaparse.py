import os
import yaml
import subprocess
import json
from typing import Dict, Optional, List, Tuple
from dotenv import load_dotenv
from langchain.docstore.document import Document

load_dotenv()

class SambaParse:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)

    def run_ingest(self, source_type: str, input_path: Optional[str] = None, additional_metadata: Optional[Dict] = None):

        # Delete Old Output Before running
        del_command = f"rm -rf {self.config['processor']['output_dir']}"
        print(f"Running command to delete previous output: {del_command}")

        subprocess.run(del_command, shell=True, check=True)

        command = [
            'unstructured-ingest',
            source_type,
            '--output-dir', self.config['processor']['output_dir'],
            '--num-processes', str(self.config['processor']['num_processes']),
        ]

        # Add partition arguments
        command.extend([
            '--strategy', self.config['partitioning']['strategy'],
            '--ocr-languages', ','.join(self.config['partitioning']['ocr_languages']),
            '--encoding', self.config['partitioning']['encoding'],
            '--fields-include', ','.join(self.config['partitioning']['fields_include']),
            '--metadata-exclude', ','.join(self.config['partitioning']['metadata_exclude']),
            '--metadata-include', ','.join(self.config['partitioning']['metadata_include']),
        ])

        if not self.config['partitioning']['pdf_infer_table_structure']:
            command.append('--pdf-infer-table-structure')

        if self.config['partitioning']['skip_infer_table_types']:
            command.extend(['--skip-infer-table-types', ','.join(self.config['partitioning']['skip_infer_table_types'])])

        if self.config['partitioning']['flatten_metadata']:
            command.append('--flatten-metadata')

        if source_type == 'local':
            if input_path is None:
                raise ValueError("Input path is required for local source type.")
            command.extend(['--input-path', '"'+input_path+'"'])

            if self.config['sources']['local']['recursive']:
                command.append('--recursive')
        elif source_type == 'confluence':
            command.extend([
                '--url', self.config['sources']['confluence']['url'],
                '--user-email', self.config['sources']['confluence']['user_email'],
                '--api-token', self.config['sources']['confluence']['api_token'],
            ])
        elif source_type == 'github':
            command.extend([
                '--url', self.config['sources']['github']['url'],
                '--git-branch', self.config['sources']['github']['branch'],
            ])
        elif source_type == 'google-drive':
            command.extend([
                '--drive-id', self.config['sources']['google_drive']['drive_id'],
                '--service-account-key', self.config['sources']['google_drive']['service_account_key'],
            ])
            if self.config['sources']['google_drive']['recursive']:
                command.append('--recursive')
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        if self.config['processor']['verbose']:
            command.append('--verbose')

        if self.config['partitioning']['partition_by_api']:
            api_key = os.getenv("UNSTRUCTURED_API_KEY")
            partition_endpoint_url = self.config['partitioning']['partition_endpoint']
            if api_key:
                command.extend(['--partition-by-api', '--api-key', api_key])
                command.extend(['--partition-endpoint', partition_endpoint_url])
            else:
                raise ValueError("UNSTRUCTURED_API_KEY environment variable is not set.")


        if self.config['chunking']['enabled']:
            command.extend([
                '--chunking-strategy', self.config['chunking']['strategy'],
                '--chunk-max-characters', str(self.config['chunking']['chunk_max_characters']),
                '--chunk-overlap', str(self.config['chunking']['chunk_overlap']),
            ])

        if self.config['embedding']['enabled']:
            command.extend([
                '--embedding-provider', self.config['embedding']['provider'],
                '--embedding-model-name', self.config['embedding']['model_name'],
            ])

        if self.config['destination_connectors']['enabled']:
            destination_type = self.config['destination_connectors']['type']
            if destination_type == 'chroma':
                command.extend([
                    'chroma',
                    '--host', self.config['destination_connectors']['chroma']['host'],
                    '--port', str(self.config['destination_connectors']['chroma']['port']),
                    '--collection-name', self.config['destination_connectors']['chroma']['collection_name'],
                    '--tenant', self.config['destination_connectors']['chroma']['tenant'],
                    '--database', self.config['destination_connectors']['chroma']['database'],
                    '--batch-size', str(self.config['destination_connectors']['batch_size']),
                ])
            elif destination_type == 'qdrant':
                command.extend([
                    'qdrant',
                    '--location', self.config['destination_connectors']['qdrant']['location'],
                    '--collection-name', self.config['destination_connectors']['qdrant']['collection_name'],
                    '--batch-size', str(self.config['destination_connectors']['batch_size']),
                ])
            else:
                raise ValueError(f"Unsupported destination connector type: {destination_type}")

        command_str = ' '.join(command)
        print(f"Running command: {command_str}")

        subprocess.run(command_str, shell=True, check=True)

        # Call the additional processing function if enabled
        if self.config['additional_processing']['enabled']:
            texts, metadata_list, langchain_docs = additional_processing(
                directory=self.config['processor']['output_dir'],
                extend_metadata=self.config['additional_processing']['extend_metadata'],
                additional_metadata=additional_metadata,
                replace_table_text=self.config['additional_processing']['replace_table_text'],
                table_text_key=self.config['additional_processing']['table_text_key'],
                return_langchain_docs=self.config['additional_processing']['return_langchain_docs']
            )
            return texts, metadata_list, langchain_docs

def additional_processing(directory: str, extend_metadata: bool, additional_metadata: Optional[Dict],
                          replace_table_text: bool, table_text_key: str, return_langchain_docs: bool):
    if os.path.isfile(directory):
        file_paths = [directory]
    else:
        file_paths = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.json')]

    texts = []
    metadata_list = []
    langchain_docs = []

    for file_path in file_paths:
        with open(file_path, 'r') as file:
            data = json.load(file)

        for element in data:
            if extend_metadata and additional_metadata:
                element['metadata'].update(additional_metadata)

            if replace_table_text and element['type'] == 'Table':
                element['text'] = element['metadata'][table_text_key]

            metadata = element['metadata'].copy()
            for key in element:
                if key not in ['text', 'metadata','embeddings']:
                    metadata[key] = element[key]
            if 'page_number' in metadata:
                metadata['page'] = metadata['page_number']
            else:
                metadata['page'] = 1

            metadata_list.append(metadata)
            texts.append(element['text'])

        if return_langchain_docs:
            langchain_docs.extend(get_langchain_docs(texts, metadata_list))

        with open(file_path, 'w') as file:
            json.dump(data, file, indent=2)

    return texts, metadata_list, langchain_docs

def get_langchain_docs(texts: List[str], metadata_list: List[Dict]) -> List[Document]:
    return [
        Document(page_content=content, metadata=metadata)
        for content, metadata in zip(texts, metadata_list)
    ]
