import logging
import time
import json
import os
from typing import List, Dict, Any, Optional, Union, Callable
import tweepy
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TwitterScraper:
    """
    Scraper for Twitter/X data using Tweepy library.
    Extracts marketing-related tweets, threads, and user profiles.
    """
    
    def __init__(self, 
                 consumer_key: str = None, 
                 consumer_secret: str = None,
                 access_token: str = None,
                 access_token_secret: str = None,
                 bearer_token: str = None):
        """
        Initialize the Twitter scraper.
        
        Args:
            consumer_key: Twitter API consumer key
            consumer_secret: Twitter API consumer secret
            access_token: Twitter API access token
            access_token_secret: Twitter API access token secret
            bearer_token: Twitter API bearer token (v2 API)
        """
        # Get credentials from environment if not provided
        self.consumer_key = consumer_key or os.environ.get('TWITTER_CONSUMER_KEY')
        self.consumer_secret = consumer_secret or os.environ.get('TWITTER_CONSUMER_SECRET')
        self.access_token = access_token or os.environ.get('TWITTER_ACCESS_TOKEN')
        self.access_token_secret = access_token_secret or os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')
        self.bearer_token = bearer_token or os.environ.get('TWITTER_BEARER_TOKEN')
        
        self.client = None
        self.api = None
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize Twitter API clients."""
        try:
            # Initialize v1 API (for features not in v2 yet)
            if all([self.consumer_key, self.consumer_secret, self.access_token, self.access_token_secret]):
                auth = tweepy.OAuth1UserHandler(
                    self.consumer_key, self.consumer_secret,
                    self.access_token, self.access_token_secret
                )
                self.api = tweepy.API(auth)
                logger.info("Initialized Twitter API v1")
            
            # Initialize v2 API (preferred for most features)
            if self.bearer_token:
                self.client = tweepy.Client(bearer_token=self.bearer_token,
                                          consumer_key=self.consumer_key,
                                          consumer_secret=self.consumer_secret,
                                          access_token=self.access_token,
                                          access_token_secret=self.access_token_secret)
                logger.info("Initialized Twitter API v2")
            
            if not self.api and not self.client:
                logger.warning("Could not initialize any Twitter API client. Please check credentials.")
        except Exception as e:
            logger.error(f"Error initializing Twitter API clients: {str(e)}")
    
    def search_tweets(self, query: str, max_results: int = 100, 
                     days_back: int = 7, include_replies: bool = False) -> List[Dict[str, Any]]:
        """
        Search for tweets matching a query.
        
        Args:
            query: Search query (can include hashtags, keywords, etc.)
            max_results: Maximum number of results to return
            days_back: How many days back to search
            include_replies: Whether to include reply tweets
            
        Returns:
            list: List of tweet data dictionaries
        """
        tweets = []
        
        try:
            if not self.client:
                logger.error("Twitter v2 API client not initialized. Cannot search tweets.")
                return tweets
            
            # Calculate start time
            start_time = datetime.utcnow() - timedelta(days=days_back)
            
            # Build query
            full_query = query
            if not include_replies:
                full_query += " -is:reply"
            
            logger.info(f"Searching tweets with query: {full_query}")
            
            # Search tweets using v2 API
            tweet_fields = ['created_at', 'public_metrics', 'entities', 'context_annotations', 'author_id', 'lang']
            user_fields = ['name', 'username', 'description', 'public_metrics']
            expansion_fields = ['author_id', 'referenced_tweets.id', 'entities.mentions.username']
            
            # Search in batches due to API limitations
            pagination_token = None
            results_count = 0
            
            while results_count < max_results:
                batch_size = min(100, max_results - results_count)  # Twitter API max batch is 100
                
                response = self.client.search_recent_tweets(
                    query=full_query,
                    start_time=start_time,
                    max_results=batch_size,
                    tweet_fields=tweet_fields,
                    user_fields=user_fields,
                    expansions=expansion_fields,
                    next_token=pagination_token
                )
                
                if not response.data:
                    break
                
                # Process tweets
                users = {user.id: user for user in response.includes.get('users', [])}
                
                for tweet in response.data:
                    tweet_data = {
                        'id': tweet.id,
                        'text': tweet.text,
                        'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                        'retweet_count': tweet.public_metrics.get('retweet_count', 0),
                        'reply_count': tweet.public_metrics.get('reply_count', 0),
                        'like_count': tweet.public_metrics.get('like_count', 0),
                        'quote_count': tweet.public_metrics.get('quote_count', 0),
                        'lang': tweet.lang,
                        'author_id': tweet.author_id
                    }
                    
                    # Add author information
                    if tweet.author_id in users:
                        user = users[tweet.author_id]
                        tweet_data['author'] = {
                            'id': user.id,
                            'username': user.username,
                            'name': user.name,
                            'description': user.description,
                            'followers_count': user.public_metrics.get('followers_count', 0),
                            'following_count': user.public_metrics.get('following_count', 0),
                            'tweet_count': user.public_metrics.get('tweet_count', 0)
                        }
                    
                    # Add entities (hashtags, URLs, mentions)
                    if hasattr(tweet, 'entities'):
                        entities = tweet.entities or {}
                        
                        tweet_data['hashtags'] = [tag.get('tag') for tag in entities.get('hashtags', [])]
                        tweet_data['urls'] = [url.get('expanded_url') for url in entities.get('urls', [])]
                        tweet_data['mentions'] = [
                            {'username': mention.get('username'), 'id': mention.get('id')} 
                            for mention in entities.get('mentions', [])
                        ]
                    
                    # Add context annotations (topics, domains)
                    if hasattr(tweet, 'context_annotations'):
                        context = tweet.context_annotations or []
                        tweet_data['context'] = [
                            {
                                'domain': item.get('domain', {}).get('name'),
                                'entity': item.get('entity', {}).get('name')
                            }
                            for item in context
                        ]
                    
                    # Process for marketing relevance
                    tweet_data['marketing_relevance'] = self._assess_marketing_relevance(tweet_data)
                    
                    tweets.append(tweet_data)
                
                results_count += len(response.data)
                
                # Check if we have more results
                meta = response.meta
                if not meta or not meta.get('next_token'):
                    break
                
                pagination_token = meta.get('next_token')
                
                # Respect rate limits
                time.sleep(2)
            
            logger.info(f"Found {len(tweets)} tweets for query: {query}")
            return tweets
            
        except Exception as e:
            logger.error(f"Error searching tweets: {str(e)}")
            return tweets
    
    def get_user_timeline(self, username: str, max_tweets: int = 100) -> List[Dict[str, Any]]:
        """
        Get tweets from a user's timeline.
        
        Args:
            username: Twitter username (without @)
            max_tweets: Maximum number of tweets to retrieve
            
        Returns:
            list: List of tweet data dictionaries
        """
        tweets = []
        
        try:
            if not self.client:
                logger.error("Twitter v2 API client not initialized. Cannot get user timeline.")
                return tweets
            
            logger.info(f"Fetching timeline for user: {username}")
            
            # Get user ID first
            user_response = self.client.get_user(username=username)
            if not user_response.data:
                logger.warning(f"User not found: {username}")
                return tweets
            
            user_id = user_response.data.id
            
            # Get user timeline
            tweet_fields = ['created_at', 'public_metrics', 'entities', 'context_annotations']
            
            # Fetch in batches
            pagination_token = None
            results_count = 0
            
            while results_count < max_tweets:
                batch_size = min(100, max_tweets - results_count)
                
                response = self.client.get_users_tweets(
                    id=user_id,
                    max_results=batch_size,
                    tweet_fields=tweet_fields,
                    exclude=['retweets', 'replies'],
                    pagination_token=pagination_token
                )
                
                if not response.data:
                    break
                
                for tweet in response.data:
                    tweet_data = {
                        'id': tweet.id,
                        'text': tweet.text,
                        'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                        'metrics': tweet.public_metrics,
                        'username': username
                    }
                    
                    # Add entities
                    if hasattr(tweet, 'entities'):
                        entities = tweet.entities or {}
                        tweet_data['hashtags'] = [tag.get('tag') for tag in entities.get('hashtags', [])]
                        tweet_data['urls'] = [url.get('expanded_url') for url in entities.get('urls', [])]
                    
                    # Process for marketing relevance
                    tweet_data['marketing_relevance'] = self._assess_marketing_relevance(tweet_data)
                    
                    tweets.append(tweet_data)
                
                results_count += len(response.data)
                
                # Check if we have more results
                meta = response.meta
                if not meta or not meta.get('next_token'):
                    break
                
                pagination_token = meta.get('next_token')
                
                # Respect rate limits
                time.sleep(2)
            
            logger.info(f"Fetched {len(tweets)} tweets from {username}'s timeline")
            return tweets
            
        except Exception as e:
            logger.error(f"Error getting user timeline: {str(e)}")
            return tweets
    
    def get_thread(self, tweet_id: str) -> List[Dict[str, Any]]:
        """
        Reconstruct a Twitter thread from a tweet ID.
        
        Args:
            tweet_id: ID of a tweet in the thread
            
        Returns:
            list: Ordered list of tweets in the thread
        """
        thread = []
        
        try:
            if not self.client:
                logger.error("Twitter v2 API client not initialized. Cannot get thread.")
                return thread
            
            logger.info(f"Fetching thread for tweet: {tweet_id}")
            
            # Get initial tweet
            tweet_fields = ['created_at', 'public_metrics', 'entities', 'conversation_id', 'author_id']
            user_fields = ['name', 'username', 'description', 'public_metrics']
            
            tweet_response = self.client.get_tweet(
                id=tweet_id,
                tweet_fields=tweet_fields,
                user_fields=user_fields,
                expansions=['author_id']
            )
            
            if not tweet_response.data:
                logger.warning(f"Tweet not found: {tweet_id}")
                return thread
            
            tweet = tweet_response.data
            conversation_id = tweet.conversation_id
            author_id = tweet.author_id
            
            # Find user info
            user = None
            if tweet_response.includes and 'users' in tweet_response.includes:
                for u in tweet_response.includes.get('users', []):
                    if u.id == author_id:
                        user = u
                        break
            
            # Get all tweets in the conversation by the same author
            # This is a simplified approach to thread reconstruction
            thread_response = self.client.search_recent_tweets(
                query=f"conversation_id:{conversation_id} from:{user.username}",
                tweet_fields=tweet_fields,
                user_fields=user_fields,
                expansions=['author_id'],
                max_results=100
            )
            
            if thread_response.data:
                # Order tweets by ID (chronological)
                ordered_tweets = sorted(thread_response.data, key=lambda t: int(t.id))
                
                for tweet in ordered_tweets:
                    tweet_data = {
                        'id': tweet.id,
                        'text': tweet.text,
                        'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                        'metrics': tweet.public_metrics,
                        'author': {
                            'id': user.id,
                            'username': user.username,
                            'name': user.name
                        } if user else None
                    }
                    
                    thread.append(tweet_data)
                
            logger.info(f"Reconstructed thread with {len(thread)} tweets")
            return thread
            
        except Exception as e:
            logger.error(f"Error getting thread: {str(e)}")
            return thread
    
    def _assess_marketing_relevance(self, tweet_data: Dict[str, Any]) -> float:
        """
        Assess how relevant a tweet is to marketing.
        
        Args:
            tweet_data: Tweet data dictionary
            
        Returns:
            float: Relevance score (0 to 1)
        """
        marketing_keywords = [
            'marketing', 'campaign', 'brand', 'advertising', 'advert', 'content', 'strategy',
            'social media', 'seo', 'ppc', 'ctr', 'conversion', 'funnel', 'lead gen', 'roi',
            'engagement', 'analytics', 'customer', 'audience', 'target', 'demographic',
            'digital marketing', 'email marketing', 'content marketing', 'growth hacking'
        ]
        
        # Check text and hashtags
        text = tweet_data.get('text', '').lower()
        hashtags = [tag.lower() for tag in tweet_data.get('hashtags', [])]
        
        # Count keyword matches
        keyword_matches = sum(1 for keyword in marketing_keywords if keyword in text)
        hashtag_matches = sum(1 for hashtag in hashtags if any(keyword in hashtag for keyword in marketing_keywords))
        
        # Calculate final score (simplified)
        # Score is between 0 and 1
        score = min(1.0, (keyword_matches * 0.1) + (hashtag_matches * 0.2))
        
        # Boost score if contains marketing hashtags
        if any(tag in ['marketing', 'digitalmarketing', 'growthhacking'] for tag in hashtags):
            score = min(1.0, score + 0.3)
        
        return score

class LinkedInScraper:
    """
    Scraper for LinkedIn data using their API (requires LinkedIn Developer account).
    Extracts company pages, posts, and marketing content.
    
    Note: LinkedIn scraping is limited by API access. This is a simplified implementation.
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """
        Initialize the LinkedIn scraper.
        
        Args:
            api_key: LinkedIn API key
            api_secret: LinkedIn API secret
        """
        # Get credentials from environment if not provided
        self.api_key = api_key or os.environ.get('LINKEDIN_API_KEY')
        self.api_secret = api_secret or os.environ.get('LINKEDIN_API_SECRET')
        
        self.authenticated = False
        if self.api_key and self.api_secret:
            self.authenticated = True
            logger.info("LinkedIn API credentials found")
        else:
            logger.warning("LinkedIn API credentials not found. Limited functionality available.")
    
    def get_company_data(self, company_id: str) -> Dict[str, Any]:
        """
        Get company data from LinkedIn.
        
        Args:
            company_id: LinkedIn company ID
            
        Returns:
            dict: Company data
        """
        if not self.authenticated:
            logger.error("LinkedIn API credentials not configured")
            return {}
        
        # This is a placeholder - actual implementation would use LinkedIn's API
        logger.info(f"Getting company data for: {company_id}")
        return {
            'id': company_id,
            'name': 'Company Name',
            'description': 'Company Description',
            'industry': 'Marketing',
            'website': 'https://example.com',
            'followers_count': 1000
        }
    
    def get_company_posts(self, company_id: str, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get company posts from LinkedIn.
        
        Args:
            company_id: LinkedIn company ID
            count: Number of posts to retrieve
            
        Returns:
            list: Company posts
        """
        if not self.authenticated:
            logger.error("LinkedIn API credentials not configured")
            return []
        
        # This is a placeholder - actual implementation would use LinkedIn's API
        logger.info(f"Getting company posts for: {company_id}")
        return [{
            'id': f"post{i}",
            'content': f"Example post {i}",
            'published_at': datetime.now().isoformat(),
            'likes_count': 100,
            'comments_count': 20
        } for i in range(count)]

# Convenience functions
def search_marketing_tweets(query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    """
    Search for marketing-related tweets.
    
    Args:
        query: Search query
        max_results: Maximum number of results
        
    Returns:
        list: Tweet data
    """
    scraper = TwitterScraper()
    marketing_query = f"{query} (marketing OR brand OR campaign OR strategy)"
    return scraper.search_tweets(marketing_query, max_results=max_results)

def get_marketing_accounts_tweets(accounts: List[str], tweets_per_account: int = 20) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get tweets from a list of marketing-focused accounts.
    
    Args:
        accounts: List of Twitter usernames
        tweets_per_account: Number of tweets per account
        
    Returns:
        dict: Mapping of accounts to their tweets
    """
    scraper = TwitterScraper()
    results = {}
    
    for account in accounts:
        results[account] = scraper.get_user_timeline(account, max_tweets=tweets_per_account)
        
    return results