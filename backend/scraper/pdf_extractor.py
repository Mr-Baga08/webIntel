import logging
import os
import tempfile
import requests
from pathlib import Path
from typing import Optional, Dict, Any
import pdfplumber
import camelot
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class PDFExtractor:
    """
    Extracts text and tables from PDF files for marketing materials.
    Uses pdfplumber for general text extraction and camelot for table extraction.
    """
    
    def __init__(self, temp_dir: Optional[str] = None):
        """
        Initialize the PDF extractor.
        
        Args:
            temp_dir: Optional temporary directory for downloaded files
        """
        self.temp_dir = temp_dir or tempfile.gettempdir()
        
    def extract_from_url(self, url: str) -> Dict[str, Any]:
        """
        Download and extract content from a PDF URL.
        
        Args:
            url: URL of the PDF to download and process
            
        Returns:
            dict: Extracted PDF content and metadata
        """
        try:
            # Create a temporary file path
            temp_path = os.path.join(self.temp_dir, f"webintel_pdf_{hash(url)}.pdf")
            
            # Download the PDF
            logger.info(f"Downloading PDF from {url}")
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Extract content from the downloaded PDF
            content = self.extract_from_file(temp_path)
            
            # Clean up the temporary file
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(f"Failed to remove temporary PDF file: {str(e)}")
            
            return content
            
        except Exception as e:
            logger.error(f"Error extracting content from PDF URL {url}: {str(e)}")
            return {
                'text': '',
                'tables': [],
                'metadata': {},
                'error': str(e)
            }
    
    def extract_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Extract content from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            dict: Extracted PDF content and metadata
        """
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"PDF file not found: {file_path}")
                
            logger.info(f"Extracting content from PDF file: {file_path}")
            
            result = {
                'text': '',
                'tables': [],
                'metadata': {},
                'toc': [],
                'pages': []
            }
            
            # Extract text and metadata using pdfplumber
            with pdfplumber.open(file_path) as pdf:
                # Extract metadata
                result['metadata'] = {
                    'page_count': len(pdf.pages),
                    'author': pdf.metadata.get('Author', ''),
                    'creator': pdf.metadata.get('Creator', ''),
                    'producer': pdf.metadata.get('Producer', ''),
                    'title': pdf.metadata.get('Title', ''),
                    'subject': pdf.metadata.get('Subject', ''),
                    'creation_date': pdf.metadata.get('CreationDate', '')
                }
                
                # Extract full text content
                full_text = []
                for i, page in enumerate(pdf.pages):
                    try:
                        page_text = page.extract_text() or ""
                        full_text.append(page_text)
                        
                        result['pages'].append({
                            'page_num': i + 1,
                            'text': page_text,
                            'width': page.width,
                            'height': page.height
                        })
                    except Exception as e:
                        logger.warning(f"Error extracting text from page {i+1}: {str(e)}")
                        result['pages'].append({
                            'page_num': i + 1,
                            'text': '',
                            'error': str(e)
                        })
                
                result['text'] = "\n\n".join(full_text)
            
            # Extract tables using camelot if available
            try:
                tables = camelot.read_pdf(file_path, pages='all')
                if tables:
                    for i, table in enumerate(tables):
                        table_df = table.df
                        result['tables'].append({
                            'table_num': i + 1,
                            'page_num': table.page,
                            'data': table_df.to_dict(orient='records'),
                            'accuracy': table.accuracy,
                            'whitespace': table.whitespace,
                            'csv': table.df.to_csv(index=False)
                        })
            except Exception as e:
                logger.warning(f"Error extracting tables with camelot: {str(e)}")
                
                # Fallback: Try to extract tables with pdfplumber
                try:
                    with pdfplumber.open(file_path) as pdf:
                        for i, page in enumerate(pdf.pages):
                            tables = page.extract_tables()
                            for j, table in enumerate(tables):
                                # Convert table to dataframe
                                df = pd.DataFrame(table[1:], columns=table[0] if table else [])
                                result['tables'].append({
                                    'table_num': len(result['tables']) + 1,
                                    'page_num': i + 1,
                                    'data': df.to_dict(orient='records'),
                                    'csv': df.to_csv(index=False)
                                })
                except Exception as e2:
                    logger.warning(f"Error extracting tables with pdfplumber: {str(e2)}")
            
            # Extract marketing-specific data if it looks like marketing material
            result.update(self._extract_marketing_data(result['text'], result['metadata']))
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting content from PDF file {file_path}: {str(e)}")
            return {
                'text': '',
                'tables': [],
                'metadata': {},
                'error': str(e)
            }
    
    def _extract_marketing_data(self, text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract marketing-specific data from PDF text.
        
        Args:
            text: Extracted text content
            metadata: PDF metadata
            
        Returns:
            dict: Marketing-specific data
        """
        marketing_data = {}
        
        # Look for case study signals
        if 'case study' in text.lower() or 'case study' in metadata.get('title', '').lower():
            marketing_data['type'] = 'case_study'
            
            # Try to extract company name
            company_candidates = []
            lines = text.split('\n')
            for i, line in enumerate(lines[:20]):  # Check first 20 lines
                if 'customer' in line.lower() or 'client' in line.lower() or 'company' in line.lower():
                    if i + 1 < len(lines) and len(lines[i+1]) > 0 and len(lines[i+1]) < 50:
                        company_candidates.append(lines[i+1])
            
            if company_candidates:
                marketing_data['company'] = company_candidates[0]
            
            # Extract challenge, solution, results sections
            sections = {}
            current_section = None
            
            # Common section headers in case studies
            section_keywords = {
                'challenge': ['challenge', 'problem', 'situation', 'background', 'objective'],
                'solution': ['solution', 'approach', 'implementation', 'process', 'strategy'],
                'results': ['results', 'outcome', 'impact', 'benefits', 'conclusion']
            }
            
            # Look for sections
            lines = text.split('\n')
            for line in lines:
                line_lower = line.lower().strip()
                
                # Check if this line is a section header
                for section, keywords in section_keywords.items():
                    if any(keyword in line_lower for keyword in keywords) and len(line) < 100:
                        current_section = section
                        sections[current_section] = []
                        break
                
                # Add content to current section if we're in one
                if current_section and line.strip() and not any(keyword in line_lower for keyword in 
                                                               [k for keywords in section_keywords.values() for k in keywords]):
                    sections[current_section].append(line)
            
            # Compile sections into final data
            for section, content in sections.items():
                marketing_data[section] = '\n'.join(content)
        
        # Look for whitepaper signals
        elif 'white paper' in text.lower() or 'whitepaper' in text.lower():
            marketing_data['type'] = 'whitepaper'
            
            # Try to extract executive summary
            if 'executive summary' in text.lower():
                parts = text.lower().split('executive summary')
                if len(parts) > 1:
                    summary_text = parts[1].split('\n\n', 1)[0] if '\n\n' in parts[1] else parts[1][:500]
                    marketing_data['executive_summary'] = summary_text
        
        # Look for marketing report signals
        elif 'report' in text.lower() or 'study' in text.lower() or 'survey' in text.lower():
            marketing_data['type'] = 'report'
            
            # Try to extract key findings
            if 'key findings' in text.lower() or 'main findings' in text.lower():
                parts = text.lower().split('key findings' if 'key findings' in text.lower() else 'main findings')
                if len(parts) > 1:
                    findings_text = parts[1].split('\n\n', 1)[0] if '\n\n' in parts[1] else parts[1][:500]
                    marketing_data['key_findings'] = findings_text
        
        return marketing_data

# Convenience function
def extract_pdf(url_or_file: str) -> Dict[str, Any]:
    """
    Extract content from a PDF URL or file path.
    
    Args:
        url_or_file: URL or file path to process
        
    Returns:
        dict: Extracted PDF content
    """
    extractor = PDFExtractor()
    
    if url_or_file.startswith(('http://', 'https://')):
        return extractor.extract_from_url(url_or_file)
    else:
        return extractor.extract_from_file(url_or_file)