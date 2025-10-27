import asyncio
import redis.asyncio as redis

async def test_redis():
    redis_url = "redis://default:RMnshw5pEDAvMNfabY4HloLlCjTm20kr@redis-11548.crce182.ap-south-1-1.ec2.redns.redis-cloud.com:11548"

    print("Testing Redis connection...")
    try:
        client = await redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
            socket_connect_timeout=5,
            socket_keepalive=True
        )

        # Test connection
        await client.ping()
        print("[OK] Redis connection successful!")

        # Test write
        await client.set("test_key", "test_value", ex=60)
        print("[OK] Redis write successful!")

        # Test read
        value = await client.get("test_key")
        print(f"[OK] Redis read successful! Value: {value}")

        # Cleanup
        await client.delete("test_key")
        await client.aclose()

        print("\n[SUCCESS] Redis is working perfectly!")

    except Exception as e:
        print(f"\n ERROR: Redis connection failed: {e}")
        print("Note: Bot will still work with in-memory cache fallback")

if __name__ == "__main__":
    asyncio.run(test_redis())
