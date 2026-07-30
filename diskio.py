#!/usr/bin/env python3
"""
iomap - Map process I/O to specific disks
Shows which processes are reading/writing to which disks
"""

import os
import time
import sys
import glob
from collections import defaultdict

def get_disk_name(dev_path):
    """Get the base disk name from a device path"""
    if not dev_path:
        return None
    
    # Handle NVMe devices (nvme0n1, nvme1n1, etc.)
    if dev_path.startswith('nvme'):
        # nvme0n1p1 -> nvme0n1
        # nvme0n1 -> nvme0n1
        if 'p' in dev_path:
            return dev_path.split('p')[0]
        return dev_path
    
    # Handle SCSI/SATA devices (sda, sdb, etc.)
    if dev_path.startswith('sd'):
        return dev_path
    
    # Handle device mapper (dm-*)
    if dev_path.startswith('dm-'):
        try:
            for mapper in glob.glob('/dev/mapper/*'):
                if os.path.realpath(mapper) == f'/dev/{dev_path}':
                    return os.path.basename(mapper)
        except:
            pass
        return dev_path
    
    return dev_path

def get_disk_for_file(path):
    """Get the disk name for a given file path"""
    try:
        # Get the device for this file
        stat = os.stat(path)
        dev = stat.st_dev
        
        # Find which mount point this file belongs to
        with open('/proc/self/mountinfo', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 5:
                    mount = parts[4]
                    if path.startswith(mount):
                        dev_name = parts[2]
                        if dev_name.startswith('/dev/'):
                            # Get the base disk name
                            disk = os.path.basename(dev_name)
                            disk = get_disk_name(disk)
                            return disk
                        break
    except:
        pass
    
    # Fallback: try to get from /proc/partitions
    try:
        with open('/proc/partitions', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    major = int(parts[0])
                    minor = int(parts[1])
                    # Check if this device matches our stat dev
                    if os.major(dev) == major and os.minor(dev) == minor:
                        return get_disk_name(parts[3])
    except:
        pass
    
    return None

def get_process_io(prev_processes=None):
    """Get I/O statistics for all processes with their file descriptors"""
    processes = {}
    try:
        for pid_path in glob.glob('/proc/[0-9]*'):
            pid = int(os.path.basename(pid_path))
            try:
                # Get process info
                with open(f'{pid_path}/cmdline', 'rb') as f:
                    cmd = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore').strip()
                    if not cmd:
                        cmd = f'[{pid}]'
                
                with open(f'{pid_path}/status', 'r') as f:
                    for line in f:
                        if line.startswith('Name:'):
                            name = line.split(':', 1)[1].strip()
                            break
                    else:
                        name = cmd.split()[0] if cmd else 'unknown'
                
                # Get I/O stats
                io_path = f'{pid_path}/io'
                io_stats = {}
                if os.path.exists(io_path):
                    with open(io_path, 'r') as f:
                        for line in f:
                            if ':' in line:
                                key, val = line.split(':', 1)
                                io_stats[key.strip()] = int(val.strip())
                
                # Find which disks this process is using
                disks = set()
                
                # Check open files
                fd_path = f'{pid_path}/fd'
                if os.path.exists(fd_path):
                    for fd in os.listdir(fd_path):
                        try:
                            link = os.readlink(f'{fd_path}/{fd}')
                            if link.startswith('/') and not link.startswith('/dev/'):
                                disk = get_disk_for_file(link)
                                if disk:
                                    disks.add(disk)
                        except:
                            continue
                
                # If no disks found, check mapped files
                if not disks:
                    maps_path = f'{pid_path}/maps'
                    if os.path.exists(maps_path):
                        with open(maps_path, 'r') as f:
                            for line in f:
                                parts = line.split()
                                if len(parts) >= 6:
                                    path = parts[-1]
                                    if path.startswith('/') and not path.startswith('/dev/'):
                                        disk = get_disk_for_file(path)
                                        if disk:
                                            disks.add(disk)
                # Use 'unknown' if no disk found
                if not disks:
                    disks = {'unknown'}
                
                # Get previous values for delta calculation
                prev_read = 0
                prev_write = 0
                if prev_processes and pid in prev_processes:
                    prev_read = prev_processes[pid]['read_bytes']
                    prev_write = prev_processes[pid]['write_bytes']
                
                processes[pid] = {
                    'name': name,
                    'cmd': cmd[:60],
                    'read_bytes': io_stats.get('read_bytes', 0),
                    'write_bytes': io_stats.get('write_bytes', 0),
                    'prev_read_bytes': prev_read,
                    'prev_write_bytes': prev_write,
                    'syscr': io_stats.get('syscr', 0),
                    'syscw': io_stats.get('syscw', 0),
                    'disks': disks
                }
            except (IOError, OSError, ValueError):
                continue
    except:
        pass
    return processes

def get_disk_stats():
    """Get disk I/O statistics"""
    disk_stats = {}
    try:
        with open('/proc/diskstats', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    dev = parts[2]
                    # Skip loop devices
                    if not dev.startswith('loop'):
                        # Handle NVMe partitions
                        if dev.startswith('nvme') and 'p' in dev:
                            # Skip partitions, only track main device
                            if not dev.split('p')[0] == dev:
                                continue
                        # Skip partition numbers for SCSI/SATA
                        if dev.startswith('sd') and len(dev) > 3 and dev[3:].isdigit():
                            continue
                        
                        read_bytes = int(parts[5]) * 512
                        write_bytes = int(parts[9]) * 512
                        disk_stats[dev] = {
                            'read_bytes': read_bytes,
                            'write_bytes': write_bytes
                        }
    except:
        pass
    return disk_stats

def get_delta(current, previous):
    """Calculate delta between current and previous stats"""
    delta = {}
    if not previous:
        return delta
    
    for key in current:
        if key in previous:
            delta[key] = {
                'read_bytes': current[key]['read_bytes'] - previous[key]['read_bytes'],
                'write_bytes': current[key]['write_bytes'] - previous[key]['write_bytes']
            }
    return delta

def format_bytes(bytes_val):
    """Format bytes to human readable"""
    if bytes_val < 0:
        bytes_val = 0
    if bytes_val >= 1024*1024*1024:
        return f"{bytes_val/(1024*1024*1024):.2f}GB"
    elif bytes_val >= 1024*1024:
        return f"{bytes_val/(1024*1024):.2f}MB"
    elif bytes_val >= 1024:
        return f"{bytes_val/1024:.2f}KB"
    else:
        return f"{bytes_val}B"

def print_process_io(processes, disk_delta, interval):
    """Print process I/O mapped to disks"""
    lines = []
    lines.append("=" * 120)
    lines.append(f"Process I/O to Disk Mapping (interval: {interval}s)")
    lines.append("=" * 120)
    
    # Group processes by disk
    disk_processes = defaultdict(list)
    for pid, proc in processes.items():
        for disk in proc['disks']:
            # Calculate per-second rates using deltas
            read_rate = (proc['read_bytes'] - proc['prev_read_bytes']) / interval if interval > 0 else 0
            write_rate = (proc['write_bytes'] - proc['prev_write_bytes']) / interval if interval > 0 else 0
            disk_processes[disk].append((pid, proc, read_rate, write_rate))
    
    # Print by disk
    for disk in sorted(disk_processes.keys()):
        lines.append(f"\nDISK: {disk}")
        lines.append("-" * 90)
        lines.append(f"{'PID':>8} {'READ/s':>15} {'WRITE/s':>15} {'CMD':<60}")
        lines.append("-" * 90)
        
        # Sort by total I/O rate
        proc_list = sorted(disk_processes[disk], key=lambda x: x[2] + x[3], reverse=True)
        
        count = 0
        for pid, proc, read_rate, write_rate in proc_list:
            if read_rate > 0 or write_rate > 0:
                lines.append(f"{pid:>8} {format_bytes(read_rate):>15}/s {format_bytes(write_rate):>15}/s {proc['cmd'][:60]:<60}")
                count += 1
                if count >= 20:
                    break
        
        if count == 0:
            lines.append(f"{'No active I/O':>8}")
    
    # Show disk I/O summary
    if disk_delta:
        lines.append("\nDISK I/O SUMMARY")
        lines.append("-" * 50)
        lines.append(f"{'DISK':<15} {'READ/s':>15} {'WRITE/s':>15}")
        lines.append("-" * 50)
        has_activity = False
        for disk, delta in disk_delta.items():
            read_rate = delta['read_bytes'] / interval if interval > 0 else 0
            write_rate = delta['write_bytes'] / interval if interval > 0 else 0
            if read_rate > 0 or write_rate > 0:
                lines.append(f"{disk:<15} {format_bytes(read_rate):>15}/s {format_bytes(write_rate):>15}/s")
                has_activity = True
        
        if not has_activity:
            lines.append(f"{'No disk I/O activity':>15}")
    
    lines.append("")
    return '\n'.join(lines)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Map process I/O to specific disks')
    parser.add_argument('-i', '--interval', type=float, default=2,
                       help='Update interval in seconds (default: 2)')
    parser.add_argument('-c', '--count', type=int, default=0,
                       help='Number of iterations (0=unlimited)')
    args = parser.parse_args()
    
    prev_processes = {}
    prev_disk_stats = {}
    count = 0
    
    try:
        while True:
            # Get current stats
            processes = get_process_io(prev_processes)
            disk_stats = get_disk_stats()
            
            # Calculate disk deltas
            disk_delta = get_delta(disk_stats, prev_disk_stats)
            
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # Print
            print(print_process_io(processes, disk_delta, args.interval))
            
            # Save for next iteration
            prev_processes = processes
            prev_disk_stats = disk_stats
            
            count += 1
            if args.count > 0 and count >= args.count:
                break
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
