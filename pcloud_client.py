import requests
import json
import os

class PCloudClient:
    def __init__(self, access_token, api_host="api.pcloud.com"):
        self.access_token = access_token
        self.api_host = api_host
        self.base_url = f"https://{api_host}"

    def upload_file(self, file_path, folder_id=0):
        """Uploads a file to pCloud and returns the file ID."""
        url = f"{self.base_url}/uploadfile"
        
        filename = os.path.basename(file_path)
        params = {
            'auth': self.access_token,
            'folderid': folder_id,
            'filename': filename,
            'nopartial': 1
        }
        
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = requests.post(url, params=params, files=files)
                result = response.json()
                
                if result.get('result') == 0:
                    return result['metadata'][0]['fileid']
                else:
                    print(f"  [pCloud Error] Upload failed: {result}")
                    return None
        except Exception as e:
            print(f"  [pCloud Error] Exception during upload: {e}")
            return None

    def get_public_link(self, file_id):
        """Generates a public link for a file ID."""
        url = f"{self.base_url}/getfilepublink"
        params = {
            'auth': self.access_token,
            'fileid': file_id
        }
        
        try:
            response = requests.get(url, params=params)
            result = response.json()
            
            if result.get('result') == 0:
                return result['link']
            else:
                print(f"  [pCloud Error] Get link failed: {result}")
                return None
        except Exception as e:
            print(f"  [pCloud Error] Exception getting link: {e}")
            return None

    def create_folder_if_not_exists(self, path_name, parent_folder_id=0):
        """Creates a folder or returns existing folder ID."""
        # Note: This is a simplified check. A proper implementation would walk the path.
        # Here we just create a folder in the parent_folder_id.
        
        # Check if exists (filtering is hard without listing). 
        # Easier to try create and catch "already exists" or list first.
        # We'll use 'createfolderifnotexists' logic manually or via API?
        # API method: createfolder
        
        url = f"{self.base_url}/createfolder"
        params = {
            'auth': self.access_token,
            'folderid': parent_folder_id,
            'name': path_name
        }
        
        response = requests.get(url, params=params)
        result = response.json()
        
        if result.get('result') == 0:
            return result['metadata']['folderid']
        elif result.get('result') == 2005: # Folder exists? (Check error codes, assume yes or list)
            # 2002? 
            # Fallback: List folder and find it.
            return self._find_folder_id(path_name, parent_folder_id)
        else:
             # Try listing to find it
             return self._find_folder_id(path_name, parent_folder_id)

    def _find_folder_id(self, name, parent_id):
        url = f"{self.base_url}/listfolder"
        params = {
            'auth': self.access_token,
            'folderid': parent_id
        }
        response = requests.get(url, params=params)
        result = response.json()
        if result.get('result') == 0:
            for item in result['metadata']['contents']:
                if item['isfolder'] and item['name'] == name:
                    return item['folderid']
        return None
