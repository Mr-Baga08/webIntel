import logging
import os
import json
import pandas as pd
import requests
import zipfile
import tempfile
from typing import Dict, Any, List, Optional, Union
from pathlib import Path

logger = logging.getLogger(__name__)

class DatasetCollector:
    """
    Collect structured datasets from public repositories like Kaggle,
    HuggingFace, or data.gov. Focuses on marketing-related datasets.
    """
    
    def __init__(self, 
                 kaggle_username: Optional[str] = None,
                 kaggle_key: Optional[str] = None,
                 hf_token: Optional[str] = None,
                 output_dir: Optional[str] = None):
        """
        Initialize the dataset collector.
        
        Args:
            kaggle_username: Kaggle username (or from env: KAGGLE_USERNAME)
            kaggle_key: Kaggle API key (or from env: KAGGLE_KEY)
            hf_token: HuggingFace API token (or from env: HF_TOKEN)
            output_dir: Directory to save datasets
        """
        # Get credentials from environment if not provided
        self.kaggle_username = kaggle_username or os.environ.get('KAGGLE_USERNAME')
        self.kaggle_key = kaggle_key or os.environ.get('KAGGLE_KEY')
        self.hf_token = hf_token or os.environ.get('HF_TOKEN')
        
        self.output_dir = output_dir or tempfile.gettempdir()
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Set up Kaggle API credentials if available
        if self.kaggle_username and self.kaggle_key:
            self._setup_kaggle_credentials()
            self.kaggle_available = True
            logger.info("Kaggle API credentials found")
        else:
            self.kaggle_available = False
            logger.warning("Kaggle API credentials not found. Set KAGGLE_USERNAME and KAGGLE_KEY environment variables.")
        
        # Initialize HuggingFace API client if token is available
        if self.hf_token:
            self.hf_available = True
            logger.info("HuggingFace API token found")
        else:
            self.hf_available = False
            logger.warning("HuggingFace API token not found. Set HF_TOKEN environment variable.")
    
    def _setup_kaggle_credentials(self):
        """Set up Kaggle API credentials."""
        kaggle_dir = os.path.expanduser('~/.kaggle')
        os.makedirs(kaggle_dir, exist_ok=True)
        
        # Create or update kaggle.json
        kaggle_creds = {
            "username": self.kaggle_username,
            "key": self.kaggle_key
        }
        
        kaggle_json_path = os.path.join(kaggle_dir, 'kaggle.json')
        
        try:
            with open(kaggle_json_path, 'w') as f:
                json.dump(kaggle_creds, f)
            
            # Set proper permissions (required by Kaggle API)
            os.chmod(kaggle_json_path, 0o600)
            logger.info("Kaggle credentials configured")
        except Exception as e:
            logger.error(f"Error setting up Kaggle credentials: {str(e)}")
    
    def search_kaggle_datasets(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for datasets on Kaggle.
        
        Args:
            query: Search query
            max_results: Maximum number of results to return
            
        Returns:
            list: List of dataset metadata
        """
        if not self.kaggle_available:
            logger.error("Kaggle API credentials not available")
            return []
        
        try:
            # Import here to avoid requiring kaggle package if not used
            from kaggle.api.kaggle_api_extended import KaggleApi
            
            api = KaggleApi()
            api.authenticate()
            
            logger.info(f"Searching Kaggle datasets with query: {query}")
            
            # Search datasets
            datasets = api.dataset_list(search=query, sort_by='relevance')
            
            # Limit results
            datasets = datasets[:max_results]
            
            # Convert to dictionaries
            results = []
            for dataset in datasets:
                results.append({
                    'ref': f"{dataset.ref}",
                    'title': dataset.title,
                    'subtitle': dataset.subtitle,
                    'description': dataset.description,
                    'url': f"https://www.kaggle.com/datasets/{dataset.ref}",
                    'size': dataset.size,
                    'lastUpdated': str(dataset.lastUpdated),
                    'downloadCount': dataset.downloadCount,
                    'voteCount': dataset.voteCount,
                    'tags': [tag.name for tag in dataset.tags] if hasattr(dataset, 'tags') else [],
                    'ownerName': dataset.ownerName
                })
            
            logger.info(f"Found {len(results)} Kaggle datasets for query: {query}")
            return results
            
        except Exception as e:
            logger.error(f"Error searching Kaggle datasets: {str(e)}")
            return []
    
    def download_kaggle_dataset(self, dataset_ref: str, extract: bool = True) -> str:
        """
        Download a dataset from Kaggle.
        
        Args:
            dataset_ref: Dataset reference (e.g., 'username/dataset-name')
            extract: Whether to extract the downloaded ZIP file
            
        Returns:
            str: Path to the downloaded dataset
        """
        if not self.kaggle_available:
            logger.error("Kaggle API credentials not available")
            return ""
        
        try:
            # Import here to avoid requiring kaggle package if not used
            from kaggle.api.kaggle_api_extended import KaggleApi
            
            api = KaggleApi()
            api.authenticate()
            
            # Create a directory for this dataset
            dataset_dir = os.path.join(self.output_dir, dataset_ref.replace('/', '-'))
            os.makedirs(dataset_dir, exist_ok=True)
            
            logger.info(f"Downloading Kaggle dataset: {dataset_ref}")
            
            # Download the dataset
            api.dataset_download_files(dataset_ref, path=dataset_dir, unzip=extract)
            
            if extract:
                logger.info(f"Dataset extracted to {dataset_dir}")
                return dataset_dir
            else:
                zip_path = os.path.join(dataset_dir, f"{dataset_ref.split('/')[-1]}.zip")
                logger.info(f"Dataset downloaded to {zip_path}")
                return zip_path
                
        except Exception as e:
            logger.error(f"Error downloading Kaggle dataset: {str(e)}")
            return ""
    
    def load_dataset(self, dataset_path: str, file_pattern: str = "*.csv") -> Dict[str, pd.DataFrame]:
        """
        Load dataset files into pandas DataFrames.
        
        Args:
            dataset_path: Path to the dataset directory
            file_pattern: File pattern to match (e.g., "*.csv")
            
        Returns:
            dict: Mapping of filenames to DataFrames
        """
        try:
            logger.info(f"Loading dataset from {dataset_path} with pattern {file_pattern}")
            
            dataset_path = Path(dataset_path)
            if not dataset_path.exists():
                logger.error(f"Dataset path does not exist: {dataset_path}")
                return {}
            
            # Find all matching files
            files = list(dataset_path.glob(file_pattern))
            
            # Load each file into a DataFrame
            dataframes = {}
            for file in files:
                try:
                    if file.suffix.lower() == '.csv':
                        df = pd.read_csv(file)
                    elif file.suffix.lower() in ['.xlsx', '.xls']:
                        df = pd.read_excel(file)
                    elif file.suffix.lower() == '.json':
                        df = pd.read_json(file)
                    else:
                        logger.warning(f"Unsupported file format: {file}")
                        continue
                    
                    dataframes[file.name] = df
                    logger.info(f"Loaded {file.name} with {len(df)} rows and {len(df.columns)} columns")
                except Exception as e:
                    logger.error(f"Error loading file {file}: {str(e)}")
            
            return dataframes
            
        except Exception as e:
            logger.error(f"Error loading dataset: {str(e)}")
            return {}
    
    def search_huggingface_datasets(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for datasets on HuggingFace.
        
        Args:
            query: Search query
            max_results: Maximum number of results to return
            
        Returns:
            list: List of dataset metadata
        """
        try:
            # Construct API URL
            api_url = f"https://huggingface.co/api/datasets?search={query}&limit={max_results}"
            
            # Set headers
            headers = {}
            if self.hf_token:
                headers['Authorization'] = f"Bearer {self.hf_token}"
            
            # Make request
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            
            # Parse response
            datasets = response.json()
            
            # Format results
            results = []
            for dataset in datasets:
                results.append({
                    'id': dataset.get('id', ''),
                    'name': dataset.get('name', ''),
                    'description': dataset.get('description', ''),
                    'tags': dataset.get('tags', []),
                    'downloads': dataset.get('downloads', 0),
                    'likes': dataset.get('likes', 0),
                    'url': f"https://huggingface.co/datasets/{dataset.get('id', '')}"
                })
            
            logger.info(f"Found {len(results)} HuggingFace datasets for query: {query}")
            return results
            
        except Exception as e:
            logger.error(f"Error searching HuggingFace datasets: {str(e)}")
            return []
    
    def download_huggingface_dataset(self, dataset_id: str) -> str:
        """
        Download a dataset from HuggingFace.
        
        Args:
            dataset_id: Dataset ID
            
        Returns:
            str: Path to the downloaded dataset
        """
        try:
            # Import here to avoid requiring datasets package if not used
            from datasets import load_dataset
            
            # Create a directory for this dataset
            dataset_dir = os.path.join(self.output_dir, f"hf-{dataset_id.replace('/', '-')}")
            os.makedirs(dataset_dir, exist_ok=True)
            
            logger.info(f"Downloading HuggingFace dataset: {dataset_id}")
            
            # Load the dataset
            dataset = load_dataset(dataset_id)
            
            # Save to disk
            dataset.save_to_disk(dataset_dir)
            
            logger.info(f"Dataset saved to {dataset_dir}")
            return dataset_dir
            
        except Exception as e:
            logger.error(f"Error downloading HuggingFace dataset: {str(e)}")
            return ""
    
    def extract_marketing_datasets(self, query: str = "marketing") -> List[Dict[str, Any]]:
        """
        Search and extract marketing-related datasets from multiple sources.
        
        Args:
            query: Search query
            
        Returns:
            list: Combined list of dataset metadata
        """
        results = []
        
        # Search Kaggle
        if self.kaggle_available:
            kaggle_results = self.search_kaggle_datasets(query)
            for result in kaggle_results:
                result['source'] = 'kaggle'
            results.extend(kaggle_results)
        
        # Search HuggingFace
        hf_results = self.search_huggingface_datasets(query)
        for result in hf_results:
            result['source'] = 'huggingface'
        results.extend(hf_results)
        
        # Filter for marketing relevance
        marketing_keywords = ['marketing', 'advertisement', 'customer', 'campaign', 'sales', 
                            'brand', 'social media', 'ecommerce', 'consumer']
        
        def marketing_relevance(dataset):
            """Calculate marketing relevance score."""
            text = ' '.join([
                dataset.get('title', ''),
                dataset.get('subtitle', ''),
                dataset.get('description', ''),
                ' '.join(dataset.get('tags', []))
            ]).lower()
            
            return sum(1 for keyword in marketing_keywords if keyword in text)
        
        # Sort by relevance
        results.sort(key=marketing_relevance, reverse=True)
        
        return results
    
    def load_marketing_dataset(self, dataset_info: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        """
        Download and load a marketing dataset based on its info.
        
        Args:
            dataset_info: Dataset metadata
            
        Returns:
            dict: Loaded DataFrames
        """
        source = dataset_info.get('source')
        
        if source == 'kaggle':
            dataset_path = self.download_kaggle_dataset(dataset_info['ref'])
            return self.load_dataset(dataset_path)
        elif source == 'huggingface':
            dataset_path = self.download_huggingface_dataset(dataset_info['id'])
            return self.load_dataset(dataset_path)
        else:
            logger.error(f"Unknown dataset source: {source}")
            return {}

# Convenience functions
def get_marketing_datasets(search_term: str = "marketing") -> List[Dict[str, Any]]:
    """
    Get marketing-related datasets.
    
    Args:
        search_term: Search term
        
    Returns:
        list: Dataset metadata
    """
    collector = DatasetCollector()
    return collector.extract_marketing_datasets(search_term)

def download_dataset(dataset_info: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """
    Download and load a dataset.
    
    Args:
        dataset_info: Dataset metadata
        
    Returns:
        dict: Loaded DataFrames
    """
    collector = DatasetCollector()
    return collector.load_marketing_dataset(dataset_info)