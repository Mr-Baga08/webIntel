import logging
import re
import json
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def detect_content_domain(text: str, metadata: Dict[str, Any]) -> str:
    """
    Detect the content domain based on text and metadata.
    
    Args:
        text: Content text
        metadata: Content metadata
        
    Returns:
        str: Detected domain ("marketing", "legal", "academic", "technical", or "general")
    """
    text_lower = text.lower()
    title = metadata.get('title', '').lower() if metadata else ''
    
    # Domain-specific keyword sets
    marketing_keywords = [
        'marketing', 'brand', 'campaign', 'customer', 'advertising', 'social media', 
        'seo', 'content marketing', 'lead generation', 'conversion rate', 'roi', 
        'market research', 'target audience', 'product launch', 'sales funnel'
    ]
    
    legal_keywords = [
        'legal', 'law', 'court', 'judge', 'attorney', 'lawyer', 'legislation', 
        'contract', 'compliance', 'regulation', 'plaintiff', 'defendant', 
        'jurisdiction', 'statute', 'liability', 'tort', 'litigation'
    ]
    
    academic_keywords = [
        'research', 'study', 'university', 'academic', 'journal', 'professor', 
        'hypothesis', 'experiment', 'literature review', 'methodology', 
        'findings', 'peer-reviewed', 'dissertation', 'thesis', 'citation'
    ]
    
    technical_keywords = [
        'software', 'programming', 'code', 'algorithm', 'database', 'api', 
        'framework', 'architecture', 'developer', 'engineering', 'deployment', 
        'interface', 'hardware', 'protocol', 'infrastructure', 'technology'
    ]
    
    # Count keyword occurrences for each domain
    marketing_count = sum(1 for keyword in marketing_keywords if keyword in text_lower or keyword in title)
    legal_count = sum(1 for keyword in legal_keywords if keyword in text_lower or keyword in title)
    academic_count = sum(1 for keyword in academic_keywords if keyword in text_lower or keyword in title)
    technical_count = sum(1 for keyword in technical_keywords if keyword in text_lower or keyword in title)
    
    # Apply weightings (title occurrences are more significant)
    title_marketing = sum(1 for keyword in marketing_keywords if keyword in title) * 2
    title_legal = sum(1 for keyword in legal_keywords if keyword in title) * 2
    title_academic = sum(1 for keyword in academic_keywords if keyword in title) * 2
    title_technical = sum(1 for keyword in technical_keywords if keyword in title) * 2
    
    marketing_count += title_marketing
    legal_count += title_legal
    academic_count += title_academic
    technical_count += title_technical
    
    # Determine the dominant domain
    domain_scores = {
        'marketing': marketing_count,
        'legal': legal_count,
        'academic': academic_count,
        'technical': technical_count
    }
    
    # If any domain has a meaningful score
    max_score = max(domain_scores.values())
    if max_score > 2:  # Threshold for domain detection
        dominant_domain = max(domain_scores, key=domain_scores.get)
        return dominant_domain
    
    # Default to general if no clear domain detected
    return 'general'

class ContentAnalyzer:
    """Base class for domain-specific content analysis."""
    
    def __init__(self, domain: str = 'general'):
        """
        Initialize the content analyzer.
        
        Args:
            domain: Content domain name
        """
        self.domain = domain
    
    def analyze_web_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze web page content.
        
        Args:
            content: Web page content
            
        Returns:
            dict: Analysis results
        """
        return {'domain': self.domain, 'content_type': 'web_page'}
    
    def analyze_pdf_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze PDF content.
        
        Args:
            content: PDF content
            
        Returns:
            dict: Analysis results
        """
        return {'domain': self.domain, 'content_type': 'pdf'}
    
    def analyze_social_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze social media content.
        
        Args:
            content: Social media content
            
        Returns:
            dict: Analysis results
        """
        return {'domain': self.domain, 'content_type': 'social'}
    
    def analyze_video_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze video content.
        
        Args:
            content: Video content
            
        Returns:
            dict: Analysis results
        """
        return {'domain': self.domain, 'content_type': 'video'}
    
    def analyze_podcast_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze podcast content.
        
        Args:
            content: Podcast content
            
        Returns:
            dict: Analysis results
        """
        return {'domain': self.domain, 'content_type': 'podcast'}
    
    def analyze_dataset_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze dataset content.
        
        Args:
            content: Dataset content
            
        Returns:
            dict: Analysis results
        """
        return {'domain': self.domain, 'content_type': 'dataset'}

class MarketingContentAnalyzer(ContentAnalyzer):
    """Marketing-specific content analyzer."""
    
    def __init__(self):
        """Initialize the marketing content analyzer."""
        super().__init__(domain='marketing')
    
    def analyze_web_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze marketing web content.
        
        Args:
            content: Web page content
            
        Returns:
            dict: Marketing analysis results
        """
        # Start with base analysis
        result = super().analyze_web_content(content)
        
        title = content.get('title', '').lower()
        text = content.get('text', '').lower()
        html = content.get('html', '')
        
        # Determine marketing content type
        if 'case study' in title or 'case study' in text[:1000]:
            result['content_type'] = 'case_study'
            
            # Try to extract company name
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                
                # Look for company in schema.org data
                for script in soup.find_all('script', {'type': 'application/ld+json'}):
                    try:
                        ld_json = json.loads(script.string)
                        if isinstance(ld_json, dict):
                            # Look for organization
                            if ld_json.get('@type') == 'Organization':
                                result['company'] = ld_json.get('name')
                            # Look for article publisher
                            elif ld_json.get('@type') == 'Article' and isinstance(ld_json.get('publisher'), dict):
                                publisher = ld_json.get('publisher')
                                if publisher.get('@type') == 'Organization':
                                    result['company'] = publisher.get('name')
                    except Exception:
                        pass
                
                # Try to find sections (challenge, solution, results)
                sections = {}
                section_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                
                for heading in section_headings:
                    heading_text = heading.get_text().lower()
                    
                    if any(term in heading_text for term in ['challenge', 'problem', 'situation']):
                        # Get text until next heading
                        content = []
                        for sibling in heading.next_siblings:
                            if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                                break
                            if sibling.get_text().strip():
                                content.append(sibling.get_text().strip())
                        sections['challenge'] = ' '.join(content)
                        
                    elif any(term in heading_text for term in ['solution', 'approach', 'strategy']):
                        content = []
                        for sibling in heading.next_siblings:
                            if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                                break
                            if sibling.get_text().strip():
                                content.append(sibling.get_text().strip())
                        sections['solution'] = ' '.join(content)
                        
                    elif any(term in heading_text for term in ['result', 'outcome', 'impact']):
                        content = []
                        for sibling in heading.next_siblings:
                            if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                                break
                            if sibling.get_text().strip():
                                content.append(sibling.get_text().strip())
                        sections['results'] = ' '.join(content)
                
                # Add sections to result
                result.update(sections)
            
        elif any(term in title for term in ['blog', 'article']):
            result['content_type'] = 'blog_post'
            
        elif any(term in title for term in ['whitepaper', 'white paper', 'report', 'study']):
            result['content_type'] = 'whitepaper'
        
        # Extract marketing keywords and topics
        marketing_topics = [
            'content marketing', 'seo', 'social media marketing', 'email marketing',
            'digital marketing', 'affiliate marketing', 'influencer marketing',
            'product marketing', 'brand management', 'market research',
            'lead generation', 'customer acquisition', 'customer retention',
            'conversion optimization', 'marketing automation', 'analytics'
        ]
        
        detected_topics = []
        for topic in marketing_topics:
            if topic in text.lower():
                detected_topics.append(topic)
                
        if detected_topics:
            result['topics'] = detected_topics
        
        return result
    
    def analyze_pdf_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze marketing PDF content.
        
        Args:
            content: PDF content
            
        Returns:
            dict: Marketing analysis results
        """
        # Start with base analysis
        result = super().analyze_pdf_content(content)
        
        title = content.get('title', '').lower()
        text = content.get('text', '').lower()
        
        # Determine marketing content type
        if 'case study' in title or 'case study' in text[:1000]:
            result['content_type'] = 'case_study'
            
            # Try to extract company name
            company_patterns = [
                r'(?:customer|client|company):\s*([A-Z][A-Za-z0-9\s&]+)',
                r'(?:customer|client|company)\s+profile:\s*([A-Z][A-Za-z0-9\s&]+)',
                r'about\s+([A-Z][A-Za-z0-9\s&]+)(?:\n|:)'
            ]
            
            for pattern in company_patterns:
                match = re.search(pattern, text)
                if match:
                    result['company'] = match.group(1).strip()
                    break
            
            # Try to find sections (challenge, solution, results)
            # Look for common section headers in case studies
            challenge_patterns = [
                r'(?:challenge|problem|situation|objective)s?(?:\n|:)(.*?)(?:(?:solution|approach|implementation|process|results|outcome|impact|benefit)s?(?:\n|:)|$)',
                r'the\s+challenge(.*?)(?:(?:solution|approach|implementation|process|results|outcome)s?|$)',
            ]
            
            solution_patterns = [
                r'(?:solution|approach|implementation|process)s?(?:\n|:)(.*?)(?:(?:results|outcome|impact|benefit)s?(?:\n|:)|$)',
                r'the\s+solution(.*?)(?:(?:results|outcome|impact|benefit)s?|$)',
            ]
            
            results_patterns = [
                r'(?:results|outcome|impact|benefit)s?(?:\n|:)(.*?)(?:(?:conclusion|summary|about)(?:\n|:)|$)',
                r'the\s+results(.*?)(?:(?:conclusion|summary|about)|$)',
            ]
            
            for pattern in challenge_patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    challenge_text = match.group(1).strip()
                    # Limit to a reasonable length
                    challenge_text = ' '.join(challenge_text.split()[:100])
                    result['challenge'] = challenge_text
                    break
                    
            for pattern in solution_patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    solution_text = match.group(1).strip()
                    # Limit to a reasonable length
                    solution_text = ' '.join(solution_text.split()[:100])
                    result['solution'] = solution_text
                    break
                    
            for pattern in results_patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    results_text = match.group(1).strip()
                    # Limit to a reasonable length
                    results_text = ' '.join(results_text.split()[:100])
                    result['results'] = results_text
                    break
            
        elif any(term in title for term in ['whitepaper', 'white paper']):
            result['content_type'] = 'whitepaper'
            
            # Try to extract executive summary
            summary_patterns = [
                r'executive\s+summary(?:\n|:)(.*?)(?:(?:introduction|background|overview)(?:\n|:)|$)',
                r'overview(?:\n|:)(.*?)(?:(?:introduction|background|challenge)(?:\n|:)|$)'
            ]
            
            for pattern in summary_patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    summary_text = match.group(1).strip()
                    # Limit to a reasonable length
                    summary_text = ' '.join(summary_text.split()[:150])
                    result['executive_summary'] = summary_text
                    break
            
        elif any(term in title for term in ['report', 'study', 'survey']):
            result['content_type'] = 'report'
            
            # Try to extract key findings
            findings_patterns = [
                r'(?:key|main)\s+findings(?:\n|:)(.*?)(?:(?:conclusion|summary|methodology|introduction)(?:\n|:)|$)',
                r'findings(?:\n|:)(.*?)(?:(?:conclusion|summary|methodology)(?:\n|:)|$)'
            ]
            
            for pattern in findings_patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    findings_text = match.group(1).strip()
                    # Limit to a reasonable length
                    findings_text = ' '.join(findings_text.split()[:200])
                    result['key_findings'] = findings_text
                    break
        
        return result
    
    def analyze_video_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze marketing video content.
        
        Args:
            content: Video content
            
        Returns:
            dict: Marketing analysis results
        """
        # Start with base analysis
        result = super().analyze_video_content(content)
        
        title = content.get('title', '').lower()
        description = content.get('description', '').lower()
        transcript = content.get('transcript', '').lower()
        
        # Determine if it's a marketing lecture
        if any(term in title for term in ['lecture', 'course', 'tutorial', 'workshop']):
            result['content_type'] = 'lecture'
            
            # Extract topics
            topics = []
            topic_patterns = [
                r'this lecture covers ([\w\s,]+)',
                r'topic[s]?:? ([\w\s,]+)',
                r'today we\'ll discuss ([\w\s,]+)',
                r'(?:in|this) this video,? (?:we|i) (?:will|\'ll) (?:talk about|discuss|cover) ([\w\s,]+)'
            ]
            
            for pattern in topic_patterns:
                matches = re.findall(pattern, description)
                topics.extend(matches)
            
            if not topics and transcript:
                # Try to find topics in the first 1000 characters of the transcript
                for pattern in topic_patterns:
                    matches = re.findall(pattern, transcript[:1000])
                    topics.extend(matches)
            
            result['topics'] = [topic.strip() for topic in topics if len(topic.strip()) > 3] if topics else []
            
            # Try to determine if it's part of a course
            course_patterns = [
                r'lecture (\d+)',
                r'part (\d+)',
                r'session (\d+)',
                r'module (\d+)'
            ]
            
            for pattern in course_patterns:
                match = re.search(pattern, title)
                if match:
                    result['lecture_number'] = match.group(1)
                    break
        
        elif any(term in title for term in ['case study', 'success story']):
            result['content_type'] = 'case_study'
            
            # Try to extract company name
            company_patterns = [
                r'(?:featuring|with|for) ([A-Z][A-Za-z0-9\s&]+)',
                r'([A-Z][A-Za-z0-9\s&]+) (?:case study|success story)'
            ]
            
            for pattern in company_patterns:
                match = re.search(pattern, title)
                if match:
                    result['company'] = match.group(1).strip()
                    break
        
        elif any(term in title for term in ['webinar', 'seminar']):
            result['content_type'] = 'webinar'
        
        elif any(term in title for term in ['interview', 'discussion', 'conversation']):
            result['content_type'] = 'interview'
        
        # Identify marketing topics
        marketing_topics = [
            'content marketing', 'seo', 'social media marketing', 'email marketing',
            'digital marketing', 'affiliate marketing', 'influencer marketing',
            'product marketing', 'brand management', 'market research',
            'lead generation', 'customer acquisition', 'customer retention',
            'conversion optimization', 'marketing automation', 'analytics'
        ]
        
        detected_topics = []
        combined_text = f"{title} {description} {transcript[:5000]}"
        
        for topic in marketing_topics:
            if topic in combined_text:
                detected_topics.append(topic)
                
        if detected_topics and 'topics' not in result:
            result['topics'] = detected_topics
        
        return result
    
    def analyze_podcast_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze marketing podcast content.
        
        Args:
            content: Podcast content
            
        Returns:
            dict: Marketing analysis results
        """
        # Start with base analysis
        result = super().analyze_podcast_content(content)
        
        title = content.get('title', '').lower()
        description = content.get('description', '').lower()
        transcript = content.get('transcript', '').lower()
        
        # Try to extract episode number
        episode_patterns = [
            r'episode (\d+)',
            r'ep\.? (\d+)',
            r'e(\d+)'
        ]
        
        for pattern in episode_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['episode_number'] = match.group(1)
                break
        
        # Try to extract podcast name
        podcast_name_patterns = [
            r'(.+?):?\s+episode \d+',
            r'(.+?):?\s+ep\.? \d+',
            r'(.+?):?\s+e\d+'
        ]
        
        for pattern in podcast_name_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['podcast_name'] = match.group(1).strip().title()
                break
        
        # Try to extract guest information
        guest_patterns = [
            r'(?:with|featuring|guest) (.+?)(?:\s+on\s+|\s+-\s+|$)',
            r'interview with (.+?)(?:\s+on\s+|\s+-\s+|$)'
        ]
        
        for pattern in guest_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['guest'] = match.group(1).strip().title()
                break
        
        # Identify marketing topics
        marketing_topics = [
            'content marketing', 'seo', 'social media marketing', 'email marketing',
            'digital marketing', 'affiliate marketing', 'influencer marketing',
            'product marketing', 'brand management', 'market research',
            'lead generation', 'customer acquisition', 'customer retention',
            'conversion optimization', 'marketing automation', 'analytics'
        ]
        
        detected_topics = []
        combined_text = f"{title} {description} {transcript[:5000]}"
        
        for topic in marketing_topics:
            if topic in combined_text:
                detected_topics.append(topic)
                
        if detected_topics:
            result['topics'] = detected_topics
        
        return result
    
    def analyze_social_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze marketing social media content.
        
        Args:
            content: Social media content
            
        Returns:
            dict: Marketing analysis results
        """
        # Start with base analysis
        result = super().analyze_social_content(content)
        
        text = content.get('text', '').lower()
        
        # Check if there are engagement metrics
        if 'retweet_count' in content or 'like_count' in content or 'reply_count' in content:
            result['engagement_metrics'] = {
                'retweets': content.get('retweet_count', 0),
                'likes': content.get('like_count', 0),
                'replies': content.get('reply_count', 0)
            }
        
        # Identify marketing hashtags
        hashtags = content.get('hashtags', [])
        marketing_hashtags = [
            tag for tag in hashtags 
            if any(term in tag.lower() for term in [
                'marketing', 'socialmedia', 'digital', 'content', 'seo', 
                'branding', 'growthhacking', 'advertising', 'marketingdigital'
            ])
        ]
        
        if marketing_hashtags:
            result['marketing_hashtags'] = marketing_hashtags
        
        # Check for marketing campaign patterns
        campaign_patterns = [
            r'new campaign[:\s]+([^\.]+)',
            r'launching[:\s]+([^\.]+)',
            r'introducing[:\s]+([^\.]+)',
            r'announcement[:\s]+([^\.]+)'
        ]
        
        for pattern in campaign_patterns:
            match = re.search(pattern, text)
            if match:
                result['campaign_mention'] = match.group(1).strip()
                result['content_type'] = 'campaign_announcement'
                break
        
        return result

class LegalContentAnalyzer(ContentAnalyzer):
    """Legal-specific content analyzer."""
    
    def __init__(self):
        """Initialize the legal content analyzer."""
        super().__init__(domain='legal')
    
    def analyze_web_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze legal web content.
        
        Args:
            content: Web page content
            
        Returns:
            dict: Legal analysis results
        """
        # Start with base analysis
        result = super().analyze_web_content(content)
        
        # Legal-specific analysis would go here
        # This is a placeholder for demonstration purposes
        
        return result
    
    # Additional legal-specific analysis methods would be implemented here

class AcademicContentAnalyzer(ContentAnalyzer):
    """Academic-specific content analyzer."""
    
    def __init__(self):
        """Initialize the academic content analyzer."""
        super().__init__(domain='academic')
    
    def analyze_web_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze academic web content.
        
        Args:
            content: Web page content
            
        Returns:
            dict: Academic analysis results
        """
        # Start with base analysis
        result = super().analyze_web_content(content)
        
        # Academic-specific analysis would go here
        # This is a placeholder for demonstration purposes
        
        return result
    
    # Additional academic-specific analysis methods would be implemented here

class TechnicalContentAnalyzer(ContentAnalyzer):
    """Technical-specific content analyzer."""
    
    def __init__(self):
        """Initialize the technical content analyzer."""
        super().__init__(domain='technical')
    
    def analyze_web_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze technical web content.
        
        Args:
            content: Web page content
            
        Returns:
            dict: Technical analysis results
        """
        # Start with base analysis
        result = super().analyze_web_content(content)
        
        # Technical-specific analysis would go here
        # This is a placeholder for demonstration purposes
        
        return result
    
    # Additional technical-specific analysis methods would be implemented here

class GeneralContentAnalyzer(ContentAnalyzer):
    """General content analyzer with no domain specialization."""
    
    def __init__(self):
        """Initialize the general content analyzer."""
        super().__init__(domain='general')
    
    # The base methods are already implemented in ContentAnalyzer

def get_domain_analyzer(domain: Optional[str] = None) -> ContentAnalyzer:
    """
    Get the appropriate domain analyzer.
    
    Args:
        domain: Domain name
        
    Returns:
        ContentAnalyzer: Domain-specific analyzer
    """
    if domain == 'marketing':
        return MarketingContentAnalyzer()
    elif domain == 'legal':
        return LegalContentAnalyzer()
    elif domain == 'academic':
        return AcademicContentAnalyzer()
    elif domain == 'technical':
        return TechnicalContentAnalyzer()
    else:
        return GeneralContentAnalyzer()