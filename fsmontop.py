#!/usr/bin/env python3
"""
fsmon - Minimal filesystem journal monitor showing only per-second rates
"""

import os
import time
import sys

def get_ext4_journal_stats():
    """
    Read JBD2 journal statistics for ext4 filesystems from /proc/fs/jbd2/
    Returns a dictionary with journal statistics including flush and log times
    """
    journal_stats = {}
    
    try:
        # Find all JBD2 devices
        jbd2_path = '/proc/fs/jbd2'
        if not os.path.exists(jbd2_path):
            return {}
        
        for device_dir in os.listdir(jbd2_path):
            device_path = os.path.join(jbd2_path, device_dir)
            device_stats = {}
            # Check for info file (aggregated stats)
            info_path = os.path.join(device_path, 'info')
            if os.path.exists(info_path):
                try:
                    with open(info_path, 'r') as f:
                        content = f.read()
                        stats = {}
                        lines = content.strip().split('\n')
                        for line in lines:
                            line = line.strip()
                            if ':' in line and 'ms' in line:
                                parts = line.split(':')
                                if len(parts) == 2:
                                    key = parts[0].strip()
                                    value = parts[1].strip().replace('ms', '').strip()
                                    try:
                                        stats[key] = float(value)
                                    except ValueError:
                                        pass
                            elif 'transactions' in line:
                                parts = line.split()
                                for i, part in enumerate(parts):
                                    if part == 'transactions':
                                        try:
                                            stats['transactions'] = int(parts[i-1])
                                        except (ValueError, IndexError):
                                            pass
                                        break
                        
                        if stats:
                            device_stats['info'] = stats
                except Exception as e:
                    pass
            # Check for history file (recent transactions)
            history_path = os.path.join(device_path, 'history')
            if os.path.exists(history_path):
                try:
                    with open(history_path, 'r') as f:
                        lines = f.readlines()
                        if len(lines) > 1:
                            # Parse the header
                            header = lines[0].strip()
                            headers = header.split()
                            
                            # Find column indices
                            flush_idx = -1
                            log_idx = -1
                            ctime_idx = -1
                            write_idx = -1
                            
                            for i, h in enumerate(headers):
                                h_lower = h.lower()
                                if h_lower == 'flush':
                                    flush_idx = i
                                elif h_lower == 'log':
                                    log_idx = i
                                elif h_lower == 'ctime':
                                    ctime_idx = i
                                elif h_lower == 'write':
                                    write_idx = i
                            
                            # Parse transaction history
                            transactions = []
                            for line in lines[1:]:
                                if not line.strip():
                                    continue
                                parts = line.split()
                                if len(parts) < len(headers):
                                    continue
                                
                                trans = {
                                    'type': parts[0] if parts else '',
                                    'tid': int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                                }
                                
                                if flush_idx >= 0 and len(parts) > flush_idx:
                                    trans['flush_ms'] = int(parts[flush_idx]) if parts[flush_idx].isdigit() else None
                                if log_idx >= 0 and len(parts) > log_idx:
                                    trans['log_ms'] = int(parts[log_idx]) if parts[log_idx].isdigit() else None
                                if ctime_idx >= 0 and len(parts) > ctime_idx:
                                    trans['ctime_ms'] = int(parts[ctime_idx]) if parts[ctime_idx].isdigit() else None
                                if write_idx >= 0 and len(parts) > write_idx:
                                    trans['write_blocks'] = int(parts[write_idx]) if parts[write_idx].isdigit() else None
                                
                                transactions.append(trans)
                            
                            if transactions:
                                device_stats['history'] = {
                                    'transactions': transactions,
                                    'headers': headers
                                }
                except Exception as e:
                    pass
            
            if device_stats:
                journal_stats[device_dir] = device_stats
    
    except Exception as e:
        pass
    
    return journal_stats

def get_xfs_stats():
    """
    Read XFS statistics from /proc/fs/xfs/stat
    Returns a dictionary with log and flush-related metrics
    """
    xfs_stats = {}
    
    try:
        with open('/proc/fs/xfs/stat', 'r') as f:
            for line in f:
                # Looking for the 'log' group
                if line.startswith('log'):
                    parts = line.strip().split()
                    # Format: log writes blocks nointernalbuf force force_sleep ...
                    if len(parts) >= 4:
                        xfs_stats['log_writes'] = int(parts[1])
                        xfs_stats['log_blocks'] = int(parts[2])
                        xfs_stats['log_force'] = int(parts[4]) if len(parts) > 4 else 0
                        xfs_stats['log_force_sleep'] = int(parts[5]) if len(parts) > 5 else 0
                
                # Looking for the 'xstrat' group (flush daemon stats)
                elif line.startswith('xstrat'):
                    parts = line.strip().split()
                    # Format: xstrat quick ...
                    if len(parts) >= 2:
                        xfs_stats['xstrat_quick'] = int(parts[1])
                
                # Looking for the 'push_ail' group (AIL flush stats)
                elif line.startswith('push_ail'):
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        xfs_stats['ail_push'] = int(parts[1])
                    if len(parts) >= 4:
                        xfs_stats['ail_push_flush'] = int(parts[3])
                
                # Looking for the extended precision 'xpc' line
                elif line.startswith('xpc'):
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        xfs_stats['flush_bytes'] = int(parts[1])
                        xfs_stats['write_bytes'] = int(parts[2])
                        xfs_stats['read_bytes'] = int(parts[3])
                        
    except FileNotFoundError:
        return {}
    except Exception as e:
        return {}
    
    return xfs_stats

def format_bytes(bytes_val):
    """Format bytes into human-readable format"""
    if bytes_val >= 1024*1024*1024:
        return f"{bytes_val/(1024*1024*1024):.2f} GB"
    elif bytes_val >= 1024*1024:
        return f"{bytes_val/(1024*1024):.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val/1024:.2f} KB"
    else:
        return f"{bytes_val} B"

def get_delta(current, previous):
    """Calculate deltas between current and previous stats"""
    delta = {}
    if not previous:
        return delta
    
    # XFS counters
    for key in ['log_writes', 'log_blocks', 'log_force', 'log_force_sleep',
                'xstrat_quick', 'ail_push', 'ail_push_flush',
                'flush_bytes', 'write_bytes', 'read_bytes']:
        if key in current and key in previous:
            try:
                delta[key] = current[key] - previous[key]
            except:
                pass
    return delta

def print_rates(ext4_stats, xfs_stats, ext4_delta, xfs_delta, interval):
    """Print only per-second rates"""
    lines = []
    lines.append("=" * 50)
    lines.append(f"Journal Rates (interval: {interval}s)")
    lines.append("=" * 50)
    
    # Ext4 rates
    if ext4_stats:
        lines.append("\nEXT4:")
        for device, data in ext4_stats.items():
            lines.append(f"  {device}:")
            if 'info' in data:
                info_delta = ext4_delta.get(device, {}).get('info_delta', {})
                trans_delta = info_delta.get('transactions_delta', 0)
                rate = trans_delta / interval if interval > 0 else 0
                lines.append(f"    Transactions: {rate:.1f}/s")
                
                if 'flushing' in data['info']:
                    lines.append(f"    Flush: {data['info']['flushing']:.1f}ms")
                if 'logging' in data['info']:
                    lines.append(f"    Log: {data['info']['logging']:.1f}ms")
    
    # XFS rates - show all metrics even if 0
    if xfs_stats:
        lines.append("\nXFS:")
        
        # Show all metrics with their rates
        for key, label in [('log_force_sleep', 'Log Force Sleep'),
                          ('log_force', 'Log Forces'), 
                          ('log_writes', 'Log Writes'),
                          ('log_blocks', 'Log Blocks'),
                          ('xstrat_quick', 'Quick Flushes'),
                          ('ail_push', 'AIL Pushes')]:
            if key in xfs_delta:
                rate = xfs_delta[key] / interval if interval > 0 else 0
            else:
                rate = 0
            lines.append(f"  {label}: {rate:.1f}/s")
        
        # Bytes rates - show even if 0
        if 'flush_bytes' in xfs_delta:
            rate = xfs_delta['flush_bytes'] / interval if interval > 0 else 0
        else:
            rate = 0
        lines.append(f"  Flush Bytes: {format_bytes(rate)}/s")
        
        if 'write_bytes' in xfs_delta:
            rate = xfs_delta['write_bytes'] / interval if interval > 0 else 0
        else:
            rate = 0
        lines.append(f"  Write Bytes: {format_bytes(rate)}/s")
    
    lines.append("")
    return '\n'.join(lines)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Filesystem journal monitor - shows only per-second rates')
    parser.add_argument('-i', '--interval', type=float, default=2, 
                       help='Update interval in seconds (default: 2)')
    parser.add_argument('-c', '--count', type=int, default=0,
                       help='Number of iterations (0=unlimited)')
    args = parser.parse_args()
    
    prev_ext4 = {}
    prev_xfs = {}
    count = 0
    
    try:
        while True:
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # Get current stats
            ext4_stats = get_ext4_journal_stats()
            xfs_stats = get_xfs_stats()
            
            # Calculate deltas
            ext4_delta = {}
            if prev_ext4:
                for device, data in ext4_stats.items():
                    if device in prev_ext4 and 'info' in data and 'info' in prev_ext4[device]:
                        device_delta = {}
                        cur_info = data['info']
                        prev_info = prev_ext4[device]['info']
                        for key in ['transactions', 'blocks', 'blocks logged']:
                            if key in cur_info and key in prev_info:
                                try:
                                    device_delta[f'{key}_delta'] = cur_info[key] - prev_info[key]
                                except:
                                    pass
                        if device_delta:
                            ext4_delta[device] = {'info_delta': device_delta}
            
            xfs_delta = get_delta(xfs_stats, prev_xfs)
            
            # Print rates
            print(print_rates(ext4_stats, xfs_stats, ext4_delta, xfs_delta, args.interval))
            
            # Save for next iteration
            prev_ext4 = ext4_stats
            prev_xfs = xfs_stats
            
            count += 1
            if args.count > 0 and count >= args.count:
                break
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
