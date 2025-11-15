"""
Main entry point for the Telegram Bot Maker
Run this file to start the bot
"""
import uvicorn
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    logger.info(f"Starting Telegram Bot Maker on {host}:{port}")
    logger.info("Press CTRL+C to stop the server")
    
    # Run the FastAPI application
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=False,  # Set to True for development
        log_level="info"
    )
