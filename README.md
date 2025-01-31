# Instagram Content Downloader API

This is a FastAPI-based API service that allows you to download Instagram reels, stories, and videos.

## Features

- Download Instagram posts
- Download Instagram reels
- Download Instagram stories (requires authentication)
- Simple REST API interface

## Setup

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the root directory with your Instagram credentials (optional, but required for story downloads):
```
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
```

3. Run the API server:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Endpoints

### GET /
- Welcome message
- No parameters required

### POST /download
Request body:
```json
{
    "url": "https://www.instagram.com/p/POST_ID/",
    "type": "post"  // Can be "post", "reel", or "story"
}
```

## Notes

- Downloaded content will be saved in the `downloads` directory
- Story downloads require authentication
- Rate limiting may apply based on Instagram's policies
- Please respect Instagram's terms of service when using this API

## Error Handling

The API returns appropriate HTTP status codes:
- 200: Success
- 400: Invalid request
- 401: Authentication required
- 500: Server error
