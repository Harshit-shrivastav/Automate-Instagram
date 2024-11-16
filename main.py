import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from instagrapi import Client
from instagrapi.exceptions import ClientError
from pathlib import Path

# Initialize Instagram client
cl = Client()

# Challenge handler for two-factor authentication
def challenge_handler(username, choice):
    print(f"Enter code (6 digits) for {username} ({choice}):")
    return input().strip()

# Database setup
DATABASE = "insta_data.db"

def setup_database():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            username TEXT PRIMARY KEY,
            follow_date TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_followed_user(username):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO follows (username, follow_date) VALUES (?, ?)", (username, datetime.now()))
    conn.commit()
    conn.close()

def get_followed_users():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM follows")
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return result

def remove_followed_user(username):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM follows WHERE username = ?", (username,))
    conn.commit()
    conn.close()

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
        print(f"Fetching likers for @{target_username}...")
        user_id = cl.user_id_from_username(target_username)
        medias = cl.user_medias_gql(user_id, amount=1)
        if not medias:
            print(f"No posts found for @{target_username}.")
            return

        media_id = medias[0].id
        likers = cl.media_likers(media_id)
        print(f"Found {len(likers)} likers for @{target_username}.")

        already_followed = get_followed_users()
        for liker in likers:
            if liker.username in already_followed:
                print(f"Skipping @{liker.username}: Already followed.")
                continue
            
            cl.user_follow(liker.pk)
            print(f"Followed @{liker.username}")
            add_followed_user(liker.username)
            await asyncio.sleep(900)  # Wait 15 minutes before following the next user
    except Exception as e:
        print(f"Error fetching likers for @{target_username}: {e}")

async def unfollow_non_followers():
    """Unfollow users who didn't follow back within 2 days."""
    try:
        followed_users = get_followed_users()
        for username in followed_users:
            user_id = cl.user_id_from_username(username)
            is_following_back = cl.user_info(user_id).following_me
            if not is_following_back:
                follow_date = datetime.strptime(get_follow_date(username), "%Y-%m-%d %H:%M:%S")
                if datetime.now() - follow_date >= timedelta(days=2):
                    cl.user_unfollow(user_id)
                    print(f"Unfollowed @{username}: Didn't follow back in 2 days.")
                    remove_followed_user(username)
                    await asyncio.sleep(600)  # Wait 10 minutes before unfollowing the next user
    except Exception as e:
        print(f"Error during unfollowing: {e}")

def get_follow_date(username):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT follow_date FROM follows WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

async def repost_media(target_usernames):
    """Fetch and repost media from target usernames."""
    for username in target_usernames:
        try:
            print(f"Fetching media for @{username}...")
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
    setup_database()
    await login()

    # Load target usernames from environment variables
    likers_source_usernames = os.getenv("IG_LIKERS_SOURCE", "").split(",")
    repost_usernames = os.getenv("IG_REPOST_USERNAMES", "").split(",")

    if not likers_source_usernames or not repost_usernames:
        raise ValueError("Target usernames must be set in environment variables.")

    while True:
        tasks = []
        for username in likers_source_usernames:
            tasks.append(fetch_likers_and_follow(username))

        tasks.append(unfollow_non_followers())
        tasks.append(repost_media(repost_usernames))

        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
