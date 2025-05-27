import redis
import json
import logging
from typing import Optional, Any, Dict
from utils.config import Config

logger = logging.getLogger(__name__)


class RedisClient:
    _instance: Optional[redis.Redis] = None

    @classmethod
    def get_instance(cls) -> redis.Redis:
        if cls._instance is None:
            try:
                cls._instance = redis.Redis(
                    host=Config.REDIS_HOST,
                    port=Config.REDIS_PORT,
                    db=Config.REDIS_DB,
                    password=Config.REDIS_PASSWORD,
                    decode_responses=False,  # Store bytes, handle decode/encode in methods
                )
                cls._instance.ping()
                logger.info(
                    f"Successfully connected to Redis at {Config.REDIS_HOST}:{Config.REDIS_PORT}"
                )
            except redis.exceptions.ConnectionError as e:
                logger.error(f"Could not connect to Redis: {e}")
                # In a real application, you might want to handle this more gracefully,
                # e.g., by falling back to a no-op cache or raising an exception.
                # For now, we'll let it raise if connection fails.
                raise
        return cls._instance

    @classmethod
    def set_value(cls, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        try:
            r = cls.get_instance()
            serialized_value = json.dumps(value)
            if ttl_seconds:
                r.setex(key, ttl_seconds, serialized_value)
            else:
                r.set(key, serialized_value)
            logger.debug(f"Set value for key '{key}' with TTL {ttl_seconds}s")
            return True
        except (redis.exceptions.RedisError, TypeError) as e:
            logger.error(f"Error setting value in Redis for key '{key}': {e}")
            return False

    @classmethod
    def get_value(cls, key: str) -> Optional[Any]:
        try:
            r = cls.get_instance()
            serialized_value = r.get(key)
            if serialized_value:
                logger.debug(f"Retrieved value for key '{key}'")
                return json.loads(serialized_value)
            logger.debug(f"No value found for key '{key}'")
            return None
        except (redis.exceptions.RedisError, TypeError) as e:
            logger.error(f"Error getting value from Redis for key '{key}': {e}")
            return None

    @classmethod
    def delete_value(cls, key: str) -> bool:
        try:
            r = cls.get_instance()
            result = r.delete(key)
            if result > 0:
                logger.debug(f"Deleted key '{key}' from Redis")
            else:
                logger.debug(f"Key '{key}' not found in Redis for deletion")
            return result > 0
        except redis.exceptions.RedisError as e:
            logger.error(f"Error deleting value from Redis for key '{key}': {e}")
            return False

    # User data specific methods
    USER_DATA_PREFIX = "user_data:"
    USER_DATA_TTL = 3600 * 24  # 24 hours

    @classmethod
    def get_user_data(cls, user_id: str) -> Dict[str, Any]:
        key = f"{cls.USER_DATA_PREFIX}{user_id}"
        data = cls.get_value(key)
        return data if isinstance(data, dict) else {}

    @classmethod
    def update_user_data(cls, user_id: str, data_to_update: Dict[str, Any]) -> bool:
        key = f"{cls.USER_DATA_PREFIX}{user_id}"
        current_data = cls.get_user_data(user_id)
        current_data.update(data_to_update)
        return cls.set_value(key, current_data, ttl_seconds=cls.USER_DATA_TTL)

    @classmethod
    def set_user_data_key(cls, user_id: str, data_key: str, value: Any) -> bool:
        key = f"{cls.USER_DATA_PREFIX}{user_id}"
        current_data = cls.get_user_data(user_id)
        current_data[data_key] = value
        return cls.set_value(key, current_data, ttl_seconds=cls.USER_DATA_TTL)

    @classmethod
    def get_user_data_key(
        cls, user_id: str, data_key: str, default: Optional[Any] = None
    ) -> Optional[Any]:
        current_data = cls.get_user_data(user_id)
        return current_data.get(data_key, default)

    @classmethod
    def delete_user_data_key(cls, user_id: str, data_key: str) -> bool:
        key = f"{cls.USER_DATA_PREFIX}{user_id}"
        current_data = cls.get_user_data(user_id)
        if data_key in current_data:
            del current_data[data_key]
            return cls.set_value(key, current_data, ttl_seconds=cls.USER_DATA_TTL)
        return False  # Key not found

    @classmethod
    def clear_user_data(cls, user_id: str) -> bool:
        key = f"{cls.USER_DATA_PREFIX}{user_id}"
        return cls.delete_value(key)

    # --- Generic Object Caching ---
    @classmethod
    def get_cached_object(cls, cache_key: str) -> Optional[Any]:
        """Retrieves a cached object from Redis."""
        try:
            r = cls.get_instance()
            value_json = r.get(cache_key)
            if value_json:
                logger.debug(f"Cache hit for key {cache_key}")
                return json.loads(value_json)
            logger.debug(f"Cache miss for key {cache_key}")
            return None
        except Exception as e:
            logger.error(f"Error getting cached object for key {cache_key}: {e}")
            return None

    @classmethod
    def set_cached_object(cls, cache_key: str, obj: Any, ex: int = 3600) -> bool:
        """Caches an object in Redis with an expiration time."""
        try:
            r = cls.get_instance()
            r.set(cache_key, json.dumps(obj), ex=ex)
            logger.debug(f"Cached object with key {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Error caching object with key {cache_key}: {e}")
            return False

    @classmethod
    def delete_cached_object(cls, cache_key: str) -> bool:
        """Deletes a cached object from Redis."""
        try:
            r = cls.get_instance()
            result = r.delete(cache_key)
            if result > 0:
                logger.debug(f"Deleted cached object with key {cache_key}")
            else:
                logger.debug(f"Key '{cache_key}' not found in Redis for deletion")
            return result > 0
        except Exception as e:
            logger.error(f"Error deleting cached object with key {cache_key}: {e}")
            return False


if __name__ == "__main__":
    # Basic test
    logging.basicConfig(level=logging.DEBUG)
    test_user_id = "12345_test"

    # Clear any old data
    RedisClient.clear_user_data(test_user_id)

    # Test setting and getting user data
    print(f"Initial data for {test_user_id}: {RedisClient.get_user_data(test_user_id)}")

    RedisClient.set_user_data_key(test_user_id, "name", "Test User")
    RedisClient.set_user_data_key(test_user_id, "state", "awaiting_something")
    print(f"After setting name and state: {RedisClient.get_user_data(test_user_id)}")

    name = RedisClient.get_user_data_key(test_user_id, "name")
    state = RedisClient.get_user_data_key(test_user_id, "state")
    print(f"Retrieved name: {name}, state: {state}")

    RedisClient.delete_user_data_key(test_user_id, "state")
    print(f"After deleting state: {RedisClient.get_user_data(test_user_id)}")

    non_existent = RedisClient.get_user_data_key(
        test_user_id, "non_existent_key", "default_val"
    )
    print(f"Non-existent key with default: {non_existent}")

    RedisClient.update_user_data(test_user_id, {"age": 30, "city": "Testville"})
    print(f"After bulk update: {RedisClient.get_user_data(test_user_id)}")

    # Test general purpose set/get/delete
    RedisClient.set_value("my_general_key", {"data": "some_info"}, ttl_seconds=60)
    retrieved_general = RedisClient.get_value("my_general_key")
    print(f"Retrieved general key: {retrieved_general}")
    RedisClient.delete_value("my_general_key")
    retrieved_general_after_delete = RedisClient.get_value("my_general_key")
    print(f"Retrieved general key after delete: {retrieved_general_after_delete}")

    print("Basic RedisClient tests complete.")
