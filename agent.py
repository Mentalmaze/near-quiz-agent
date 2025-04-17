from nearai.agents.environment import Environment
import tweepy
import json
import os
from datetime import datetime, timezone
import time

class TwitterMonitor:
    def __init__(self, env: Environment):
        self.env = env
        self.api = self._setup_twitter_api()
        self.last_check_time = datetime.now(timezone.utc)

    def _setup_twitter_api(self):
        # Get credentials from environment variables
        bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
        if not bearer_token:
            self.env.add_agent_log("Error: Twitter bearer token not found in environment variables", level=3)
            return None
        return tweepy.Client(bearer_token=bearer_token)

    def check_mentions(self):
        if not self.api:
            return None
        
        try:
            # Get the bot's user ID (should be stored in config)
            bot_username = os.getenv("TWITTER_BOT_USERNAME", "MentalMazeBot")
            bot_user = self.api.get_user(username=bot_username)
            
            # Search for mentions since last check
            mentions = self.api.get_mentions(
                bot_user.data.id,
                since_id=self.last_check_time.strftime('%Y%m%d%H%M'),
                tweet_fields=['created_at', 'text', 'author_id']
            )
            
            self.last_check_time = datetime.now(timezone.utc)
            return mentions.data if mentions.data else []
            
        except Exception as e:
            self.env.add_agent_log(f"Error checking mentions: {str(e)}", level=3)
            return None

    def parse_tweet_content(self, tweet):
        """Parse tweet content for quiz parameters"""
        try:
            text = tweet.text.lower()
            params = {
                'source_tweet_url': f"https://twitter.com/user/status/{tweet.id}",
                'num_questions': 1,  # default
                'reward_scheme': 'equal',  # default
                'gatepass_amount': 1,  # default NEAR tokens
                'game_duration': 3600  # default 1 hour in seconds
            }
            
            # Extract parameters from tweet text
            if 'questions:' in text:
                num = text.split('questions:')[1].split()[0]
                if num.isdigit():
                    params['num_questions'] = int(num)
            
            if 'reward:' in text:
                reward = text.split('reward:')[1].split()[0]
                if reward in ['equal', 'proportional', 'winner-takes-all']:
                    params['reward_scheme'] = reward
            
            if 'gatepass:' in text:
                amount = text.split('gatepass:')[1].split()[0]
                if amount.replace('.', '').isdigit():
                    params['gatepass_amount'] = float(amount)
            
            if 'duration:' in text:
                duration = text.split('duration:')[1].split()[0]
                if duration.isdigit():
                    params['game_duration'] = int(duration) * 3600  # Convert hours to seconds
            
            return params
            
        except Exception as e:
            self.env.add_agent_log(f"Error parsing tweet content: {str(e)}", level=3)
            return None

AI_PROMPT = """
You are an AI agent designed to create and manage quiz games on the NEAR blockchain platform MentalMaze. Follow these instructions to generate engaging and interactive quizzes:

## Instructions for the LLM:

1. **Quiz Generation from Social Content**:
   - Monitor X (Twitter) for mentions.
   - Parse tweet/thread content for quiz material.
   - Generate the specified number of questions (default to 1 if not specified).

2. **Game Configuration Processing**:
   - Parse reward distribution parameters.
   - Validate gatepass amount.
   - Set game duration.
   - Handle game metadata.

3. **Blockchain Integration**:
   - Deploy the quiz contract to the NEAR chain.
   - Store game data in the database via API.
   - Generate a unique game identifier.

4. **Response Generation**:
   - Create a game URL in the format: www.mentalmaze/game/:randomid.
   - Return the playable game link to the user.

5. **Error Handling**:
   - Handle invalid input parameters.
   - Manage failed blockchain transactions.
   - Address API connectivity issues.
   - Resolve content parsing errors.

6. **Security Considerations**:
   - Validate all input parameters.
   - Ensure secure blockchain transactions.
   - Protect against malicious content.

## Expected Output:
- Confirmation of game creation.
- Unique game URL.
- Transaction hash (optional).

Make the output easy to integrate into frontend apps or chatbots. Ensure the quiz feels like a mini-game and optionally add a theme (e.g., "🧠 Quiz Quest: Space Edition!")."""


def run(env: Environment):
    # Initialize Twitter monitor
    twitter_monitor = TwitterMonitor(env)
    
    while True:
        # Check for new mentions
        mentions = twitter_monitor.check_mentions()
        
        if mentions:
            for mention in mentions:
                # Parse tweet content for game parameters
                params = twitter_monitor.parse_tweet_content(mention)
                
                if params:
                    prompt = {
                        "role": "system",
                        "content": AI_PROMPT,
                        "parameters": params
                    }
                    
                    # Generate quiz based on tweet content
                    result = env.completion([prompt] + env.list_messages())
                    
                    # Add the result to conversation history
                    env.add_reply(result)
                    
                    # Log successful quiz generation
                    env.add_agent_log(f"Generated quiz for tweet {params['source_tweet_url']}", level=1)
                else:
                    env.add_agent_log(f"Failed to parse tweet content", level=2)
        
        # Wait for 60 seconds before next check
        time.sleep(60)
        
    env.request_user_input()

run(env)
