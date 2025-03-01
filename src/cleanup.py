import docker
import logging

logger = logging.getLogger(__name__)

def cleanup_all_shell_containers(return_count=False):
    """Clean up any containers that were created by our shell script"""
    logger.info("Cleaning up all interactive shell containers...")
    
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True)
        
        found = 0
        for container in containers:
            # Look for our containers (those with a name starting with 'interactive-shell')
            if container.name.startswith('interactive-shell'):
                logger.info(f"Found container: {container.name} (status: {container.status})")
                found += 1
                
                try:
                    if container.status == 'running':
                        logger.info(f"Stopping container: {container.name}")
                        container.stop(timeout=1)
                    
                    logger.info(f"Removing container: {container.name}")
                    container.remove(force=True)
                    logger.info(f"Successfully removed: {container.name}")
                except Exception as e:
                    logger.error(f"Error removing container {container.name}: {e}")
        
        logger.info(f"Cleanup complete. Found and processed {found} containers.")
        
        if return_count:
            return found
        return 0
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        if return_count:
            return 0
        return 1

# For backward compatibility with code that expects cleanup_containers
def cleanup_containers(return_count=False):
    """Alias for cleanup_all_shell_containers for backward compatibility"""
    return cleanup_all_shell_containers(return_count=return_count)
