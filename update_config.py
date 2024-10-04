import yaml
import sys
import os
import re
from typing import Dict, Any

def update_config(kit_name: str) -> None:
    kit_path = os.path.join(kit_name)
    config_path = os.path.join(kit_path, 'config.yaml')
    makefile_path = os.path.join(kit_path, 'Makefile')

    # Update config.yaml
    with open(config_path, 'r') as file:
        config: Dict[str, Any] = yaml.safe_load(file)

    # Update config as per production requirements
    if 'prod_mode' in config:
        config['prod_mode'] = True

    if 'embedding_model' in config:
        embedding_model = config['embedding_model']
        if isinstance(embedding_model, dict):
            embedding_model['type'] = 'sambastudio'
            embedding_model['batch_size'] = 32
            embedding_model['coe'] = False

    with open(config_path, 'w') as file:
        yaml.dump(config, file)

    # Update STREAMLIT_PORT in the Makefile
    if os.path.exists(makefile_path):
        with open(makefile_path, 'r') as file:
            makefile_content = file.read()

        # Replace the STREAMLIT_PORT variable value
        new_makefile_content = re.sub(
            r'^(STREAMLIT_PORT\s*:=\s*)\d+',
            r'\g<1>443',
            makefile_content,
            flags=re.MULTILINE
        )

        with open(makefile_path, 'w') as file:
            file.write(new_makefile_content)
        print(f'Updated STREAMLIT_PORT to 443 in {makefile_path}')
    else:
        print(f'Makefile not found at {makefile_path}. Skipping STREAMLIT_PORT update.')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python update_config.py <kit_name>')
        sys.exit(1)
    kit_name = sys.argv[1]
    update_config(kit_name)