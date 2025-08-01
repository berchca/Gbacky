import hashlib
from command_runner import run_with_timeout

class CancellationError(Exception):
    """Custom exception for handling user-requested cancellations."""
    pass

def copy_file_with_watchdog(src_path, dst_path, status_update_callback, cancellation_check_callback, log_callback, io_timeout=45, progress_callback=None):
    """
    Copies a file chunk by chunk with a watchdog timeout on each I/O operation
    to prevent hangs on network filesystems.
    """
    import os
    status_update_callback(f"Copying vault to Google Drive... (this may take a while)")
    f_dst = None
    try:
        if cancellation_check_callback(): raise CancellationError("Backup cancelled by user.")
        
        # Get file size for progress tracking
        file_size = os.path.getsize(src_path)
        bytes_copied = 0
        
        # The critical part: time out the open() call for the network destination.
        f_dst = run_with_timeout(open, args=(dst_path, 'wb'), timeout=io_timeout)

        with open(src_path, 'rb') as f_src:
            while True:
                # Reading from local disk is fast and doesn't need a watchdog.
                chunk = f_src.read(4 * 1024 * 1024)
                if cancellation_check_callback():
                    raise CancellationError("Backup cancelled by user during file copy.")
                if not chunk:
                    break
                # Writing to network disk needs the watchdog.
                run_with_timeout(f_dst.write, args=(chunk,), timeout=io_timeout)
                
                # Update progress
                bytes_copied += len(chunk)
                if progress_callback and file_size > 0:
                    progress_percentage = int((bytes_copied * 100) / file_size)
                    progress_callback(progress_percentage)
        
        # Clear progress bar when copy is complete
        if progress_callback:
            progress_callback(0)
    except TimeoutError as e:
        # This is the specific error for a hung network drive.
        raise IOError(f"Google Drive is not responding during file copy: {e}") from e
    except (IOError, OSError) as e:
        # This is for other file errors like permissions, disk full, etc.
        raise IOError(f"A file error occurred during copy to Google Drive: {e}") from e
    finally:
        if f_dst:
            try:
                # Closing the file can also hang on a dead network mount.
                run_with_timeout(f_dst.close, timeout=io_timeout)
            except (IOError, OSError, TimeoutError) as e:
                # Log this, but don't re-raise as the primary error is more important.
                log_callback(f"Warning: failed to close destination file handle: {e}")

def calculate_sha256_with_watchdog(file_path, status_update_callback, cancellation_check_callback, log_callback, io_timeout=45, progress_callback=None):
    """
    Calculates SHA256 with a watchdog timeout on each read operation to prevent hangs.
    """
    import os
    status_update_callback("Verifying remote file integrity...")
    sha256_hash = hashlib.sha256()
    f_remote = None
    try:
        # Time out the open() call for the remote file.
        if cancellation_check_callback(): raise CancellationError("Backup cancelled by user.")
        
        # Get file size for progress tracking
        file_size = os.path.getsize(file_path)
        bytes_processed = 0
        
        f_remote = run_with_timeout(open, args=(file_path, 'rb'), timeout=io_timeout)
        while True:
            byte_block = run_with_timeout(f_remote.read, args=(4 * 1024 * 1024,), timeout=io_timeout)  # Use 4MB chunks for consistency
            if cancellation_check_callback():
                raise CancellationError("Backup cancelled by user during hashing.")
            if not byte_block:
                break
            sha256_hash.update(byte_block)
            
            # Update progress
            bytes_processed += len(byte_block)
            if progress_callback and file_size > 0:
                progress_percentage = int((bytes_processed * 100) / file_size)
                progress_callback(progress_percentage)
        return sha256_hash.hexdigest()
    except TimeoutError as e:
        # This is the specific error for a hung network drive.
        raise IOError(f"Google Drive is not responding during file verification: {e}") from e
    except (IOError, OSError) as e:
        # This is for other file errors like permissions, disk full, etc.
        raise IOError(f"A file error occurred during verification on Google Drive: {e}") from e
    finally:
        if f_remote:
            try:
                # Closing the remote file can also hang.
                run_with_timeout(f_remote.close, timeout=io_timeout)
            except (IOError, OSError, TimeoutError) as e:
                log_callback(f"Warning: failed to close remote file handle for hashing: {e}")

def calculate_sha256_local(file_path, status_update_callback, cancellation_check_callback):
    """Calculates the SHA256 hash of a local file without a watchdog."""
    status_update_callback("Verifying local file integrity...")
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while True:
                if cancellation_check_callback():
                    raise CancellationError("Backup cancelled by user during local file hashing.")
                byte_block = f.read(4 * 1024 * 1024)
                if not byte_block:
                    break
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except (IOError, OSError) as e:
        raise IOError(f"Failed during local file hashing: {e}") from e
