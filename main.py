import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from instagrapi import Client
from instagrapi.exceptions import ClientError

# Initialize Instagram client
cl = Client()

# Database setup
DATABASE = "insta_data.db"

def setup_database():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            username TEXT PRIMARY KEY,
            user_id INTEGER,
            follow_date TIMESTAMP,
            is_following_me INTEGER
        )
    """)
    conn.commit()
    conn.close()

def add_followed_user(username, user_id, is_following_me):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO follows (username, user_id, follow_date, is_following_me)
        VALUES (?, ?, ?, ?)
    """, (username, user_id, datetime.now(), int(is_following_me)))
    conn.commit()
    conn.close()

def get_followed_users():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, user_id, is_following_me FROM follows")
    result = cursor.fetchall()
    conn.close()
    return result

def update_follow_status(user_id, is_following_me):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE follows
        SET is_following_me = ?
        WHERE user_id = ?
    """, (int(is_following_me), user_id))
    conn.commit()
    conn.close()

def remove_followed_user(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM follows WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_follow_date(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT follow_date FROM follows WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

async def login():
    """Login using credentials from environment variables."""
    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    if not username or not password:
        raise ValueError("Instagram username and password must be set in environment variables.")
    
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

        followed_users = {user[0] for user in get_followed_users()}
        for liker in likers:
            if liker.username in followed_users:
                print(f"Skipping @{liker.username}: Already followed.")
                continue
            
            cl.user_follow(liker.pk)
            print(f"Followed @{liker.username}")
            add_followed_user(liker.username, liker.pk, False)
            await asyncio.sleep(900)  # Wait 15 minutes before following the next user
    except Exception as e:
        print(f"Error fetching likers for @{target_username}: {e}")

async def unfollow_non_followers():
    """Unfollow users who didn't follow back within 2 days."""
    try:
        followed_users = get_followed_users()
        for username, user_id, is_following_me in followed_users:
            if is_following_me:
                print(f"Skipping @{username}: Already following back.")
                continue

            user_info = cl.user_info(user_id)
            update_follow_status(user_id, user_info.is_following_me)

            if not user_info.is_following_me:
                follow_date = datetime.strptime(get_follow_date(user_id), "%Y-%m-%d %H:%M:%S")
                if datetime.now() - follow_date >= timedelta(days=2):
                    cl.user_unfollow(user_id)
                    print(f"Unfollowed @{username}: Didn't follow back in 2 days.")
                    remove_followed_user(user_id)
                    await asyncio.sleep(600)  # Wait 10 minutes before unfollowing the next user
    except Exception as e:
        print(f"Error during unfollowing: {e}")

async def repost_media(target_usernames):
    """Fetch and repost media (photos or videos) from target usernames, restricted to posting between 8 AM and 11 PM IST."""
    ist = timezone('Asia/Kolkata')  # Define IST timezone

    for username in target_usernames:
        try:
            # Check current time in IST
            current_time = datetime.now(ist)
            if current_time.hour < 8 or current_time.hour >= 23:
                print("Outside posting hours (8 AM to 11 PM IST). Skipping repost.")
                await asyncio.sleep(3600)  # Wait an hour before rechecking
                continue

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

            # Repost photo or video based on media type
            if media.media_type == 1:  # Photo
                media_path = cl.photo_download(media.pk)
                cl.photo_upload(media_path, caption=media.caption_text)
                print(f"Reposted photo from @{username}.")
            elif media.media_type == 2:  # Video
                media_path = cl.video_download(media.pk)
                cl.video_upload(media_path, caption=media.caption_text)
                print(f"Reposted video from @{username}.")
            else:
                print(f"Unsupported media type from @{username}. Skipping.")

            # Clean up downloaded media
            Path(media_path).unlink()

            await asyncio.sleep(7200)  # Wait 2 hours before reposting
        except Exception as e:
            print(f"Error reposting media from @{username}: {e}")

async def main():
    """Main function to orchestrate tasks."""
    setup_database()
    await login()

    # Load target usernames from environment variables
    likers_source_usernames = os.getenv("IG_LIKERS_SOURCE", "").split(",")

    if not likers_source_usernames:
        raise ValueError("Target usernames must be set in environment variables.")

    while True:
        tasks = []
        for username in likers_source_usernames:
            tasks.append(fetch_likers_and_follow(username))
        tasks.append(unfollow_non_followers())
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
