import os
import asyncio
from instagrapi import Client
from instagrapi.exceptions import ClientError
from pathlib import Path

# Initialize the Instagram client
cl = Client()

# Challenge handler for two-factor authentication
def challenge_handler(username, choice):
    print(f"Enter code (6 digits) for {username} ({choice}):")
    return input().strip()

async def login():
    """Login using credentials from environment variables."""
    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    if not username or not password:
        raise ValueError("Instagram username and password must be set in environment variables.")
    
    cl.challenge_code_handler = challenge_handler
    try:
        try:
            cl.load_settings("settings.json")
            print("Loaded settings from 'settings.json'.")
        except FileNotFoundError:
            print("'settings.json' not found. Proceeding with login.")
        
        cl.login(username, password)
        cl.dump_settings("settings.json")
        print("Login successful. Session saved to 'settings.json'.")
    except ClientError as e:
        print(f"Error during login: {e}")
        raise

async def fetch_likers_and_follow(target_username):
    """Fetch likers of the latest post from a username and follow them."""
    try:
        user_id = cl.user_id_from_username(target_username)
        medias = cl.user_medias_gql(user_id, amount=1)
        if not medias:
            print(f"No posts found for @{target_username}.")
            return

        media_id = medias[0].id
        likers = cl.media_likers(media_id)

        for liker in likers:
            await asyncio.sleep(900)  # Wait 15 minutes before following each user
            cl.user_follow(liker.pk)
            print(f"Followed {liker.username}")
    except Exception as e:
        print(f"Error fetching likers for @{target_username}: {e}")

async def repost_media(target_usernames):
    """Fetch and repost media from target usernames."""
    for username in target_usernames:
        try:
            user_id = cl.user_id_from_username(username)
            medias = cl.user_medias_gql(user_id, amount=1)
            if not medias:
                print(f"No posts found for @{username}.")
                continue

            media = medias[0]
            if not media.caption_text:
                print(f"Skipped media from @{username}: No caption.")
                continue

            # Download and repost media
            media_path = cl.photo_download(media.pk)
            cl.photo_upload(media_path, caption=media.caption_text)
            print(f"Reposted media from @{username}.")
            Path(media_path).unlink()  # Clean up downloaded media
            await asyncio.sleep(7200)  # Wait 2 hours before reposting
        except Exception as e:
            print(f"Error reposting media from @{username}: {e}")

async def main():
    """Main function to orchestrate tasks."""
    await login()

    # Load target usernames from environment variables
    likers_source_usernames = os.getenv("IG_LIKERS_SOURCE", "").split(",")
    repost_usernames = os.getenv("IG_REPOST_USERNAMES", "").split(",")

    if not likers_source_usernames or not repost_usernames:
        raise ValueError("Target usernames must be set in environment variables.")

    tasks = []
    for username in likers_source_usernames:
        tasks.append(fetch_likers_and_follow(username))

    tasks.append(repost_media(repost_usernames))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
