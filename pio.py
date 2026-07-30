#!/usr/bin/env python3
"""
Process I/O Monitor - Display PID, Read IO/s, Write IO/s, calls, and Process Name
"""

import os
import sys
import time
import glob
from datetime import datetime

def get_process_io(pid):
    """
    Read I/O statistics for a process from /proc/[pid]/io
    Returns a tuple of (read_bytes, write_bytes, syscr, syscw) or zeros if unavailable
    """
    try:
        with open(f'/proc/{pid}/io', 'r') as f:
            read_bytes = 0
            write_bytes = 0
            syscr = 0  # read I/O operations count
            syscw = 0  # write I/O operations count
            for line in f:
                if line.startswith('read_bytes:'):
                    read_bytes = int(line.split()[1])
                elif line.startswith('write_bytes:'):
                    write_bytes = int(line.split()[1])
                elif line.startswith('syscr:'):
                    syscr = int(line.split()[1])
                elif line.startswith('syscw:'):
                    syscw = int(line.split()[1])
            return read_bytes, write_bytes, syscr, syscw
    except (FileNotFoundError, IOError, ValueError):
        return 0, 0, 0, 0

def get_process_name(pid):
    """
    Get the process name (comm) for a process from /proc/[pid]/comm
    """
    try:
        with open(f'/proc/{pid}/comm', 'r') as f:
            return f.read().strip()
    except (FileNotFoundError, IOError):
        return '[unknown]'

def get_all_processes():
    """
    Get a list of all process PIDs
    """
    pids = []
    for proc_dir in glob.glob('/proc/[0-9]*'):
        try:
            pid = int(os.path.basename(proc_dir))
            pids.append(pid)
        except ValueError:
            continue
    return pids

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
    """
    Format bytes into human-readable format
    """
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f}G"
    elif bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.2f}M"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f}K"
    else:
        return f"{bytes_val}B"

def format_calls(calls):
    """
    Format calls for display
    """
    if calls == 0:
        return "0"
    elif calls >= 1000000:
        return f"{calls/1000000:.2f}M"
    elif calls >= 1000:
        return f"{calls/1000:.2f}K"
    else:
        return f"{calls:.1f}"

def format_throughput(bytes_per_sec):
    """
    Format throughput in human-readable format
    """
    if bytes_per_sec >= 1024 * 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024 * 1024):.2f} GB/s"
    elif bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.2f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.2f} KB/s"
    else:
        return f"{bytes_per_sec:.1f} B/s"

def print_process_io(processes_io, interval, show_all=False, disk_delta=None):
    """
    Print I/O statistics for processes
    """

    lines = []
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
    print('\n'.join(lines))
    # if not processes_io:
    #     print("  No processes with I/O activity found")
    #     return
    
    # Sort by total I/O (read + write) descending
    sorted_processes = sorted(processes_io, key=lambda x: x['total_bytes_per_sec'], reverse=True)
    
    # Display header
    print("\n" + "=" * 80)
    print(f"  PROCESS I/O STATISTICS (since last {interval:.1f}s interval)")
    print("=" * 80)
    print(f"\n  {'PID':<8} {'Read Calls/s':<13} {'Write Calls/s':<14} "
          f"{'Read B/s':<14} {'Write B/s':<14} {'Name':<20}")
    print("  " + "-" * 78)
    
    count = 0
    for proc in sorted_processes:
        if not show_all and proc['read_bytes_per_sec'] == 0 and proc['write_bytes_per_sec'] == 0:
            continue
        
        if not show_all and count >= 20:
            print("  ... (showing top 20, use --all to see all)")
            break
        
        read_calls = format_calls(proc['read_calls_per_sec'])
        write_calls = format_calls(proc['write_calls_per_sec'])
        read_throughput = format_throughput(proc['read_bytes_per_sec'])
        write_throughput = format_throughput(proc['write_bytes_per_sec'])
        
        name = proc['name']
        if len(name) > 20:
            name = name[:17] + "..."
        
        print(f"  {proc['pid']:<8} {read_calls:<13} {write_calls:<14} "
              f"{read_throughput:<14} {write_throughput:<14} {name:<20}")
        count += 1
    
    total_read = sum(p['read_bytes_per_sec'] for p in sorted_processes)
    total_write = sum(p['write_bytes_per_sec'] for p in sorted_processes)
    total_read_calls = format_calls(sum(p['read_calls_per_sec'] for p in sorted_processes))
    total_write_calls = format_calls(sum(p['write_calls_per_sec'] for p in sorted_processes))
    total_read_mb_s = total_read / (1024 * 1024)
    total_write_mb_s = total_write / (1024 * 1024)
    total_read_throughput = format_throughput(total_read)
    total_write_throughput = format_throughput(total_write)
    
    print("  " + "-" * 78)
    print(f"  {'Total':<8} {total_read_calls:<13} {total_write_calls:<14} "
          f"{total_read_throughput:<14} {total_write_throughput:<14}")
    print("=" * 80)

def clear_screen():
    """Clear the terminal screen"""
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Display process I/O statistics')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='Interval between samples in seconds (default: 1.0)')
    parser.add_argument('-a', '--all', action='store_true',
                        help='Show all processes, including those with zero I/O')
    parser.add_argument('-n', '--count', type=int, default=0,
                        help='Number of times to display statistics (0 = infinite)')
    parser.add_argument('--no-clear', action='store_true',
                        help='Do not clear screen between updates')
    parser.add_argument('--pid', type=int, help='Monitor only specific PID')
    args = parser.parse_args()
    
    print(f"Process I/O Monitor - Press Ctrl+C to stop")
    print(f"  Interval: {args.interval}s")
    print(f"  Show all: {args.all}")
    if args.pid:
        print(f"  Monitoring only PID: {args.pid}")
    print()
    
    # Store previous I/O stats
    prev_io = {}
    iteration = 0
    prev_disk_stats = {}
    
    try:
        while True:
            iteration += 1
            
            # Get current I/O stats for all processes
            current_io = {}
            if args.pid:
                # Monitor only specific PID
                pids = [args.pid]
            else:
                pids = get_all_processes()
            
            for pid in pids:
                read_bytes, write_bytes, syscr, syscw = get_process_io(pid)
                if read_bytes > 0 or write_bytes > 0 or syscr > 0 or syscw > 0:
                    name = get_process_name(pid)
                    current_io[pid] = {
                        'read_bytes': read_bytes,
                        'write_bytes': write_bytes,
                        'syscr': syscr,
                        'syscw': syscw,
                        'name': name
                    }
            
            # Get current disk stats
            disk_stats = get_disk_stats()

            # Calculate disk deltas
            disk_delta = get_delta(disk_stats, prev_disk_stats)
            
            # Calculate rates
            processes_io = []
            if prev_io:
                for pid, stats in current_io.items():
                    if pid in prev_io:
                        prev_stats = prev_io[pid]
                        # Handle counter wrap (shouldn't happen for /proc/pid/io)
                        read_delta = stats['read_bytes'] - prev_stats['read_bytes']
                        write_delta = stats['write_bytes'] - prev_stats['write_bytes']
                        syscr_delta = stats['syscr'] - prev_stats['syscr']
                        syscw_delta = stats['syscw'] - prev_stats['syscw']
                        
                        # If the process was restarted, counters might be lower
                        if read_delta < 0:
                            read_delta = stats['read_bytes']
                        if write_delta < 0:
                            write_delta = stats['write_bytes']
                        if syscr_delta < 0:
                            syscr_delta = stats['syscr']
                        if syscw_delta < 0:
                            syscw_delta = stats['syscw']
                        
                        read_per_sec = read_delta / args.interval
                        write_per_sec = write_delta / args.interval
                        read_calls_per_sec = syscr_delta / args.interval
                        write_calls_per_sec = syscw_delta / args.interval
                        
                        # Only include processes with non-zero I/O (for display)
                        if read_per_sec > 0 or write_per_sec > 0 or args.all:
                            processes_io.append({
                                'pid': pid,
                                'read_bytes_per_sec': read_per_sec,
                                'write_bytes_per_sec': write_per_sec,
                                'total_bytes_per_sec': read_per_sec + write_per_sec,
                                'read_calls_per_sec': read_calls_per_sec,
                                'write_calls_per_sec': write_calls_per_sec,
                                'total_calls_per_sec': read_calls_per_sec + write_calls_per_sec,
                                'name': stats['name']
                            })
            
            # Clear screen for better display
            if not args.no_clear:
                clear_screen()
            
            # Print timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"  Time: {timestamp}  |  Iteration: {iteration}")
            
            # Print statistics
            print_process_io(processes_io, args.interval, args.all, disk_delta)
            
            # Check if we need to exit
            if args.count > 0 and iteration >= args.count:
                break
            
            # Store current stats for next iteration
            prev_io = current_io
            prev_disk_stats = disk_stats
            
            # Wait for the next interval
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)

if __name__ == "__main__":
    main()
