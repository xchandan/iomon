#!/usr/bin/env python3
import time
import sys
import os
import glob
import socket
import subprocess
from datetime import datetime

KB = 1024
MB = KB * 1024
GB = MB * 1024

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

def format_bytes(bytes_val):
    """
    Format bytes into human-readable format
    """
    if bytes_val >= GB:
        return f"{bytes_val / GB:.2f}G"
    elif bytes_val >= MB:
        return f"{bytes_val / MB:.2f}M"
    elif bytes_val >= KB:
        return f"{bytes_val / KB:.2f}K"
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
    return f"{format_bytes(bytes_per_sec)}/s"

def print_process_io(processes_io, interval, max_count=10):
    """
    Print I/O statistics for processes
    """
    
    # Sort by total I/O (read + write) descending
    sorted_processes = sorted(processes_io, key=lambda x: x['total_bytes_per_sec'], reverse=True)
    
    # Display header
    print(f"\nPROCESS I/O STATISTICS")
    print("-" * 80)
    print(f"{'PID':<8} {'Read Calls/s':<13} {'Write Calls/s':<14} "
          f"{'Read B/s':<14} {'Write B/s':<14} {'Name':<20}")
    print("-" * 80)
    
    count = 0
    for proc in sorted_processes:
        #if proc['read_bytes_per_sec'] == 0 and proc['write_bytes_per_sec'] == 0:
        #    continue
        
        if count >= max_count:
            break
        
        read_calls = format_calls(proc['read_calls_per_sec'])
        write_calls = format_calls(proc['write_calls_per_sec'])
        read_throughput = format_throughput(proc['read_bytes_per_sec'])
        write_throughput = format_throughput(proc['write_bytes_per_sec'])
        
        name = proc['name']
        if len(name) > 20:
            name = name[:17] + "..."
        
        print(f"{proc['pid']:<8} {read_calls:<13} {write_calls:<14} "
              f"{read_throughput:<14} {write_throughput:<14} {name:<20}")
        count += 1
    
    total_read = sum(p['read_bytes_per_sec'] for p in sorted_processes)
    total_write = sum(p['write_bytes_per_sec'] for p in sorted_processes)
    total_read_calls = format_calls(sum(p['read_calls_per_sec'] for p in sorted_processes))
    total_write_calls = format_calls(sum(p['write_calls_per_sec'] for p in sorted_processes))
    total_read_mb_s = total_read / MB
    total_write_mb_s = total_write / MB
    total_read_throughput = format_throughput(total_read)
    total_write_throughput = format_throughput(total_write)
    

def read_cpu_stats():
    """
    Read the first line (total cpu stats) from /proc/stat
    Returns a tuple of (stats_list, procs_blocked)
    """
    try:
        with open('/proc/stat', 'r') as f:
            cpu_stats = None
            procs_blocked = None
            
            for line in f:
                if line.startswith('cpu '):
                    parts = line.strip().split()
                    cpu_stats = [int(x) for x in parts[1:]]
                elif line.startswith('procs_blocked'):
                    procs_blocked = int(line.strip().split()[1])
                
                # Once we have both values, we can stop reading
                if cpu_stats is not None and procs_blocked is not None:
                    break
            
            if cpu_stats is None:
                raise ValueError("Could not find 'cpu ' line in /proc/stat")
            if procs_blocked is None:
                raise ValueError("Could not find 'procs_blocked' in /proc/stat")
            
            return cpu_stats, procs_blocked
            
    except FileNotFoundError:
        print("Error: /proc/stat not found. This script only works on Linux.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading /proc/stat: {e}")
        sys.exit(1)

def read_psi_io():
    """
    Read PSI (Pressure Stall Information) for I/O from /proc/pressure/io
    Returns a tuple of (avg10, avg60, avg300, total)
    """
    try:
        with open('/proc/pressure/io', 'r') as f:
            content = f.read().strip()
            
            # Parse the line: "some avg10=0.00 avg60=0.00 avg300=0.00 total=0"
            parts = content.split()
            
            avg10 = float(parts[1].split('=')[1])
            avg60 = float(parts[2].split('=')[1])
            avg300 = float(parts[3].split('=')[1])
            total = int(parts[4].split('=')[1])
            
            return avg10, avg60, avg300, total
            
    except FileNotFoundError:
        # PSI might not be available on older kernels or if not enabled
        return None, None, None, None
    except Exception as e:
        # Silent fail for PSI errors
        return None, None, None, None

def get_load_avg():
    """
    Read system load average from /proc/loadavg
    Returns a tuple of (load1, load5, load15, running, total)
    """
    try:
        with open('/proc/loadavg', 'r') as f:
            parts = f.read().strip().split()
            load1 = float(parts[0])
            load5 = float(parts[1])
            load15 = float(parts[2])
            running = int(parts[3].split('/')[0])
            total = int(parts[3].split('/')[1])
            return load1, load5, load15, running, total
    except Exception as e:
        return 0.0, 0.0, 0.0, 0, 0

def get_memory_stats():
    """
    Read memory statistics from /proc/meminfo
    Returns a dictionary with memory metrics
    """
    mem_stats = {}
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                key = parts[0].rstrip(':')
                value = int(parts[1])
                mem_stats[key] = value * KB
    except Exception as e:
        return {}
    
    # Calculate derived metrics
    if 'MemTotal' in mem_stats and 'MemAvailable' in mem_stats:
        mem_stats['MemUsed'] = mem_stats['MemTotal'] - mem_stats['MemAvailable']
        mem_stats['MemUsedPercent'] = (mem_stats['MemUsed'] / mem_stats['MemTotal']) * 100
        mem_stats['MemAvailablePercent'] = (mem_stats['MemAvailable'] / mem_stats['MemTotal']) * 100
    
    if 'SwapTotal' in mem_stats and 'SwapFree' in mem_stats:
        mem_stats['SwapUsed'] = mem_stats['SwapTotal'] - mem_stats['SwapFree']
        mem_stats['SwapUsedPercent'] = (mem_stats['SwapUsed'] / mem_stats['SwapTotal']) * 100 if mem_stats['SwapTotal'] > 0 else 0
    
    return mem_stats

def get_cpu_percent(stats1, stats2):
    """
    Calculate CPU usage percentage between two samples
    Returns dictionary with CPU metrics
    """
    if not stats1 or not stats2:
        return {}
    
    # Fields: user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice
    # Calculate deltas
    delta_user = stats2[0] - stats1[0]
    delta_nice = stats2[1] - stats1[1]
    delta_system = stats2[2] - stats1[2]
    delta_idle = stats2[3] - stats1[3]
    delta_iowait = stats2[4] - stats1[4]
    delta_irq = stats2[5] - stats1[5]
    delta_softirq = stats2[6] - stats1[6]
    delta_steal = stats2[7] - stats1[7]
    
    total = (delta_user + delta_nice + delta_system + delta_idle + 
             delta_iowait + delta_irq + delta_softirq + delta_steal)
    
    if total <= 0:
        return {}
    
    return {
        'user': (delta_user / total) * 100,
        'nice': (delta_nice / total) * 100,
        'system': (delta_system / total) * 100,
        'idle': (delta_idle / total) * 100,
        'iowait': (delta_iowait / total) * 100,
        'irq': (delta_irq / total) * 100,
        'softirq': (delta_softirq / total) * 100,
        'steal': (delta_steal / total) * 100,
        'total_used': 100 - ((delta_idle / total) * 100)
    }

def calculate_total_time(stats):
    """
    Calculate total CPU time from stats.
    """
    return sum(stats[:8])  # Sum first 8 fields

def format_psi_value(value):
    """Format PSI value for display, handling None values"""
    if value is None:
        return "N/A"
    return f"{value:>6.2f}%"

def clear_screen():
    """Clear the terminal screen"""
    os.system('clear' if os.name == 'posix' else 'cls')

def get_disk_stats():
    """
    Read disk statistics from /proc/diskstats
    Returns a dictionary with disk stats including reads, writes, and I/O operations
    """
    disk_stats = {}
    
    try:
        with open('/proc/diskstats', 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 14:  # Need at least 14 fields for full stats
                    continue
                
                # Major and minor numbers
                major = parts[0]
                minor = parts[1]
                device = parts[2]
                
                # Skip non-disk devices (like partitions)
                # Only include devices that end with a letter (like sda, nvme0n1)
                # or have no numbers at the end (like sda, not sda1)
                if ((not device.startswith('nvme') and device.endswith(tuple('0123456789'))) or
                        (device.startswith('nvme') and 'p' in device)):
                    # This is a partition, skip it
                    continue
                
                # Parse the fields (11 core fields + 3 optional for newer kernels)
                # Fields: 0:maj,1:min,2:dev,3:reads,4:reads_merged,5:sectors_read,
                # 6:read_time,7:writes,8:writes_merged,9:sectors_written,
                # 10:write_time,11:io_in_progress,12:io_time,13:weighted_io_time
                
                reads_completed = int(parts[3])
                reads_merged = int(parts[4])
                sectors_read = int(parts[5])
                read_time_ms = int(parts[6])
                
                writes_completed = int(parts[7])
                writes_merged = int(parts[8])
                sectors_written = int(parts[9])
                write_time_ms = int(parts[10])
                
                io_in_progress = int(parts[11])
                io_time_ms = int(parts[12])
                weighted_io_time_ms = int(parts[13]) if len(parts) > 13 else 0
                
                # Calculate total I/O operations
                total_ios = reads_completed + writes_completed
                
                disk_stats[device] = {
                    'reads': reads_completed,
                    'writes': writes_completed,
                    'total_ios': total_ios,
                    'sectors_read': sectors_read,
                    'sectors_written': sectors_written,
                    'read_time_ms': read_time_ms,
                    'write_time_ms': write_time_ms,
                    'io_in_progress': io_in_progress,
                    'io_time_ms': io_time_ms,
                    'weighted_io_time_ms': weighted_io_time_ms,
                    'major': major,
                    'minor': minor
                }
                
    except FileNotFoundError:
        print("Error: /proc/diskstats not found. This script only works on Linux.")
        return {}
    except Exception as e:
        print(f"Error reading /proc/diskstats: {e}")
        return {}
    return disk_stats

def calculate_disk_metrics(stats1, stats2, interval):
    """
    Calculate disk metrics between two samples
    Returns dictionary with IOPS, throughput, and utilization metrics
    """
    metrics = {}
    
    for device in stats1:
        if device not in stats2:
            continue
        
        s1 = stats1[device]
        s2 = stats2[device]
        
        # Calculate deltas
        delta_reads = s2['reads'] - s1['reads']
        delta_writes = s2['writes'] - s1['writes']
        delta_total = s2['total_ios'] - s1['total_ios']
        
        delta_sectors_read = s2['sectors_read'] - s1['sectors_read']
        delta_sectors_written = s2['sectors_written'] - s1['sectors_written']
        
        delta_read_time = s2['read_time_ms'] - s1['read_time_ms']
        delta_write_time = s2['write_time_ms'] - s1['write_time_ms']
        delta_io_time = s2['io_time_ms'] - s1['io_time_ms']
        
        # Calculate IOPS (operations per second)
        read_iops = delta_reads / interval if interval > 0 else 0
        write_iops = delta_writes / interval if interval > 0 else 0
        total_iops = delta_total / interval if interval > 0 else 0
        
        # Calculate throughput (MB/s)
        # Each sector is 512 bytes
        read_mb_s = (delta_sectors_read * 512) / (MB * interval) if interval > 0 else 0
        write_mb_s = (delta_sectors_written * 512) / (MB * interval) if interval > 0 else 0
        total_mb_s = read_mb_s + write_mb_s
        
        # Calculate average latency (ms per operation)
        read_avg_latency = delta_read_time / delta_reads if delta_reads > 0 else 0
        write_avg_latency = delta_write_time / delta_writes if delta_writes > 0 else 0
        total_avg_latency = (delta_read_time + delta_write_time) / delta_total if delta_total > 0 else 0
        
        # Calculate utilization (% of time device was busy)
        utilization = (delta_io_time / (interval * 1000)) * 100 if interval > 0 else 0
        
        # Calculate average queue size
        avg_queue_size = (s2['weighted_io_time_ms'] - s1['weighted_io_time_ms']) / (interval * 1000) if interval > 0 else 0
        
        metrics[device] = {
            'read_iops': read_iops,
            'write_iops': write_iops,
            'total_iops': total_iops,
            'read_mb_s': read_mb_s,
            'write_mb_s': write_mb_s,
            'total_mb_s': total_mb_s,
            'read_avg_latency': read_avg_latency,
            'write_avg_latency': write_avg_latency,
            'total_avg_latency': total_avg_latency,
            'utilization': utilization,
            'avg_queue_size': avg_queue_size,
            'io_in_progress': s2['io_in_progress']
        }
    
    return metrics

def format_disk_metrics(metrics):
    """
    Format disk metrics for display
    """
    if not metrics:
        return "  No disk metrics available"
    
    output = []
    output.append("\nDISK I/O STATISTICS")
    output.append("-" * 80)
    output.append(f"{'Device':<10} {'Read IOPS':<10} {'Write IOPS':<10} {'Total IOPS':<10} "
                  f"{'Read MB/s':<10} {'Write MB/s':<10} {'Util%':<8} {'Avg Q'}")
    output.append("-" * 80)
    
    for device, stats in sorted(metrics.items()):
        output.append(
            f"{device:<10} "
            f"{stats['read_iops']:<10.1f} "
            f"{stats['write_iops']:<10.1f} "
            f"{stats['total_iops']:<10.1f} "
            f"{stats['read_mb_s']:<10.2f} "
            f"{stats['write_mb_s']:<10.2f} "
            f"{stats['utilization']:<8.2f}% "
            f"{stats['avg_queue_size']:<6.2f}"
        )
    
    return '\n'.join(output)

def print_cpu_metrics(cpu_metrics):
    """Print CPU metrics in a formatted way"""
    if not cpu_metrics:
        return "  CPU metrics not available"
    
    output = []
    output.append(f"{'CPU USAGE':<15}: "
                  f"{'User':<5} {cpu_metrics['user']:>3.1f}% "
                  f"{'Sys':<5} {cpu_metrics['system']:>3.1f}% "
                  f"{'IOwt':<5} {cpu_metrics['iowait']:>3.1f}% "
                  f"{'Idle':<5} {cpu_metrics['idle']:>3.1f}% "
                  f"{'Used':<5} {cpu_metrics['total_used']:>3.1f}%")

    return '\n'.join(output)

def print_memory_metrics(mem_stats):
    """Print memory metrics in a formatted way"""
    if not mem_stats:
        return "  Memory metrics not available"
    
    output = []

    # Memory
    mem_total = format_bytes(mem_stats.get('MemTotal', 0))
    mem_used = format_bytes(mem_stats.get('MemUsed', 0))
    mem_available = format_bytes(mem_stats.get('MemAvailable', 0))
    mem_used_pct = mem_stats.get('MemUsedPercent', 0)
    
    output.append(f"{'MEMORY USAGE':<15}: "
                  f"{'Total':<5} {mem_total:>8} "
                  f"{'Used':<5} {mem_used:>8} "
                  f"{'Avail':<5} {mem_available:>8} "
                  f"{'Used%':<5} {mem_used_pct:>6.1f}%")

    # Swap
    swap_total = format_bytes(mem_stats.get('SwapTotal', 0))
    if swap_total != '0B':
        swap_used = format_bytes(mem_stats.get('SwapUsed', 0))
        swap_free = format_bytes(mem_stats.get('SwapTotal', 0)
                                 - mem_stats.get('SwapUsed', 0))
        swap_used_pct = mem_stats.get('SwapUsedPercent', 0)
        
        output.append(f"{'SWAP USAGE':<15}: "
                      f"{'Total':<5} {swap_total:>8} "
                      f"{'Used':<5} {swap_used:>8} "
                      f"{'Free':<5} {swap_free:>8} "
                      f"{'Used%':<5} {swap_used_pct:>6.1f}%")

    
    return '\n'.join(output)

def print_load_avg(load1, load5, load15, running, blocked, total):
    """Print load average in a formatted way"""
    output = []
    output.append(f"{'TIME':<15}: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"{'HOSTNAME':<15}: {socket.gethostname()}")
    output.append(f"{'TASKS':<15}: "
                  f"{running}[Running]/{blocked}[Blocked]/{total}[Total]")
    output.append(f"{'LOAD AVERAGE':<15}: "
                  f"{load1:<6.2f} "
                  f"{load5:<6.2f} "
                  f"{load15:<6.2f}")

    
    return '\n'.join(output)

def print_io_psi(avg10, avg60, avg300, total):
    output = []
    output.append(f"{'I/O PSI':<15}: "
                  f"{avg10:<6.2f} "
                  f"{avg60:<6.2f} "
                  f"{avg300:<6.2f}")
    return '\n'.join(output)

def main():
    # Set the interval between measurements (in seconds)
    interval = 1.0
    
    # Handle optional command line argument for interval
    if len(sys.argv) > 1:
        try:
            interval = float(sys.argv[1])
        except ValueError:
            print(f"Warning: Invalid interval '{sys.argv[1]}'. Using default 1.0 second.")
    
    # Check if PSI is available
    psi_available = os.path.exists('/proc/pressure/io')
    
    # Print header based on PSI availability
    if psi_available:
        separator = "-" * 80
    else:
        separator = "-" * 45
    
    try:
        # First readings
        prev_io = {}
        stats1, _ = read_cpu_stats()
        disk_stats1 = get_disk_stats()
        
        while True:
            # Clear screen for better display
            clear_screen()

            # Print header
            print("SYSTEM INFO")
            print(separator)

            # --- CPU Metrics ---
            stats2, procs_blocked = read_cpu_stats()

            # --- Load Average ---
            load1, load5, load15, running, total = get_load_avg()
            print(print_load_avg(load1, load5, load15, running, procs_blocked, total))

            # Read PSI I/O metrics
            avg10, avg60, avg300, total = read_psi_io()
            print(print_io_psi(avg10, avg60, avg300, total))

            print()
            cpu_metrics = get_cpu_percent(stats1, stats2)
            print(print_cpu_metrics(cpu_metrics))

            # --- Memory Metrics ---
            mem_stats = get_memory_stats()
            print(print_memory_metrics(mem_stats))

            # --- Disk I/O Metrics ---
            disk_stats2 = get_disk_stats()
            disk_metrics = calculate_disk_metrics(disk_stats1, disk_stats2, interval)
            print(format_disk_metrics(disk_metrics))
            
            pids = get_all_processes()
            
            current_io = {}
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
                        
                        read_per_sec = read_delta / interval
                        write_per_sec = write_delta / interval
                        read_calls_per_sec = syscr_delta / interval
                        write_calls_per_sec = syscw_delta / interval
                        
                        # Only include processes with non-zero I/O (for display)
                        if True or read_per_sec > 0 or write_per_sec > 0:
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
                            
            # Print statistics
            print_process_io(processes_io, interval)

            # Shift the stats for the next iteration
            stats1 = stats2
            disk_stats1 = disk_stats2
            prev_io = current_io
            
            # Wait for the next interval
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)

if __name__ == "__main__":
    main()
