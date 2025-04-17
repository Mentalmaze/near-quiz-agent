from nearai.agents.environment import Environment
import tweepy
import json
import os
from datetime import datetime, timezone
import time
import traceback
from typing import Optional, Dict, Any
import uuid


class MentalMazeAgent:
    def __init__(self, env: Environment):
        self.env = env
        self.api_client = self._setup_twitter_api()
        self.last_check_time = datetime.now(timezone.utc)

    def _setup_twitter_api(self) -> Optional[tweepy.Client]:
        """Initialize Twitter API client with credentials"""
        try:
            # Get credentials from environment variables
            credentials = {
                "consumer_key": self.env.env_vars.get("X_CONSUMER_KEY"),
                "consumer_secret": self.env.env_vars.get("X_CONSUMER_SECRET"),
                "access_token": self.env.env_vars.get("X_ACCESS_TOKEN"),
                "access_token_secret": self.env.env_vars.get("X_ACCESS_TOKEN_SECRET"),
            }

            # Validate credentials
            missing = [k for k, v in credentials.items() if not v]
            if missing:
                self.env.add_agent_log(
                    f"Missing Twitter credentials: {', '.join(missing)}", level=3
                )
                return None

            return tweepy.Client(**credentials)

        except Exception as e:
            self.env.add_agent_log(f"Twitter API setup failed: {str(e)}", level=3)
            return None

    def process_mention(self, mention: Dict[str, Any]) -> None:
        """Process a single Twitter mention"""
        try:
            # Generate unique game ID
            game_id = str(uuid.uuid4())[:8]
            mention_key = f"mention-{mention.id}-game-{game_id}"

            # Check if already processed
            existing = self.env.get_agent_data_by_key(mention_key)
            if existing:
                status = existing.get("value", {}).get("status")
                if status == "complete":
                    self.env.add_agent_log(
                        f"Mention {mention.id} already processed", level=1
                    )
                    return
                elif status == "error":
                    self.env.add_agent_log(
                        f"Mention {mention.id} previously errored", level=2
                    )
                    return

            # Mark as processing
            self.env.save_agent_data(mention_key, {"status": "processing"})

            # Parse mention parameters
            params = self._parse_mention_params(mention)
            if not params:
                raise ValueError("Failed to parse mention parameters")

            # Generate quiz from mention content
            quiz_data = self._generate_quiz(params)

            # Deploy to blockchain
            tx_hash = self._deploy_to_blockchain(quiz_data, game_id)

            # Generate response
            game_url = f"www.mentalmaze.com/game/{game_id}"
            response = self._create_response(game_url, tx_hash)

            # Reply to tweet
            self._reply_to_tweet(mention.id, response)

            # Mark as complete
            self.env.save_agent_data(
                mention_key,
                {"status": "complete", "game_id": game_id, "tx_hash": tx_hash},
            )

        except Exception as e:
            self.env.add_agent_log(
                f"Error processing mention {mention.id}: {str(e)}", level=3
            )
            self.env.save_agent_data(mention_key, {"status": "error", "error": str(e)})

    def _parse_mention_params(self, mention: Dict[str, Any]) -> Dict[str, Any]:
        """Parse mention text for quiz parameters"""
        text = mention.text.lower()
        return {
            "source_tweet_url": f"https://twitter.com/user/status/{mention.id}",
            "num_questions": self._extract_param(text, "questions:", 1),
            "reward_scheme": self._extract_param(text, "reward:", "equal"),
            "gatepass_amount": self._extract_param(text, "gatepass:", 1.0),
            "game_duration": self._extract_param(text, "duration:", 3600),
        }

    def _extract_param(self, text: str, prefix: str, default: Any) -> Any:
        """Helper to extract parameters from tweet text"""
        try:
            if prefix in text:
                value = text.split(prefix)[1].split()[0]
                if isinstance(default, int):
                    return int(value)
                elif isinstance(default, float):
                    return float(value)
                return value
        except:
            pass
        return default

    def _generate_quiz(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate quiz based on parameters"""
        prompt = {
            "role": "system",
            "content": f"""Generate a quiz based on the following tweet at {params['source_tweet_url']}.
            Create {params['num_questions']} multiple choice questions.
            The quiz should run for {params['game_duration']} seconds.
            The reward distribution should be {params['reward_scheme']}.
            Entry fee is {params['gatepass_amount']} tokens.

            Return the quiz in JSON format with:
            - questions: array of questions with text and 4 choices
            - correct_answers: array of correct answer indices
            - metadata: containing reward_scheme, duration, and entry_fee""",
            "parameters": params,
        }
        result = self.env.completion([prompt] + self.env.list_messages())
        return json.loads(result) if isinstance(result, str) else result

    def _deploy_to_blockchain(self, quiz_data: Dict[str, Any], game_id: str) -> str:
        """Deploy quiz to NEAR blockchain"""
        # TODO: Implement blockchain deployment
        return f"mock_tx_hash_{game_id}"

    def _create_response(self, game_url: str, tx_hash: str) -> str:
        """Create Twitter response message"""
        return (
            f"🎮 Your quiz is ready! Play now at {game_url}\n\nTransaction: {tx_hash}"
        )

    def _reply_to_tweet(self, tweet_id: int, message: str) -> None:
        """Reply to the original tweet"""
        if self.api_client:
            try:
                self.api_client.create_tweet(
                    text=message, in_reply_to_tweet_id=tweet_id
                )
            except Exception as e:
                self.env.add_agent_log(f"Failed to reply to tweet: {str(e)}", level=3)

    def monitor_mentions(self) -> None:
        """Main monitoring loop"""
        if not self.api_client:
            self.env.add_agent_log("Twitter API client not initialized", level=3)
            return

        try:
            # Get bot's user info
            bot_username = self.env.env_vars.get(
                "TWITTER_BOT_USERNAME", "MentalMazeBot"
            )
            bot_user = self.api_client.get_user(username=bot_username)

            # Get mentions since last check
            mentions = self.api_client.get_mentions(
                bot_user.data.id,
                since_id=self.last_check_time.strftime("%Y%m%d%H%M"),
                tweet_fields=["created_at", "text", "author_id"],
            )

            self.last_check_time = datetime.now(timezone.utc)

            if mentions.data:
                for mention in mentions.data:
                    self.process_mention(mention)

        except Exception as e:
            self.env.add_agent_log(f"Error checking mentions: {str(e)}", level=3)


def run(env: Environment):
    agent = MentalMazeAgent(env)

    while True:
        agent.monitor_mentions()
        time.sleep(60)  # Check every minute

    env.request_user_input()


# run(env)
