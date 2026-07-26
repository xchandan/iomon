#!/usr/bin/env python3
import os
import glob
import time

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

def print_ext4_journal_stats(stats):
    """Print ext4 journal statistics in a formatted way"""
    if not stats:
        return "  No ext4 journal statistics available"
    
    output = []
    output.append("  EXT4 JOURNAL (JBD2) STATISTICS")
    output.append("  " + "-" * 70)
    
    for device, data in sorted(stats.items()):
        output.append(f"  Device: {device}")
        
        # Print aggregated stats
        if 'info' in data:
            s = data['info']
            output.append(f"    Transactions: {s.get('transactions', 'N/A')}")
            output.append(f"    Avg Running: {s.get('running', 0):.1f}ms")
            output.append(f"    Avg Locking: {s.get('locking', 0):.1f}ms")
            output.append(f"    🔴 Avg Flushing: {s.get('flushing', 0):.1f}ms  ← I/O flush time")
            output.append(f"    🟡 Avg Logging: {s.get('logging', 0):.1f}ms   ← Journal log time")
            output.append(f"    Avg Handle Count: {s.get('handle count', 0):.0f}")
            output.append(f"    Avg Blocks: {s.get('blocks', 0):.0f}")
            output.append(f"    Avg Blocks Logged: {s.get('blocks logged', 0):.0f}")
        
        # Print recent transactions
        if 'history' in data:
            trans = data['history']['transactions']
            output.append(f"    Recent Transactions (last 5):")
            
            # Find available columns
            has_flush = any('flush_ms' in t and t['flush_ms'] is not None for t in trans)
            has_log = any('log_ms' in t and t['log_ms'] is not None for t in trans)
            has_ctime = any('ctime_ms' in t and t['ctime_ms'] is not None for t in trans)
            
            # Build header
            header_parts = ["    "]
            header_parts.append(f"{'Type':<4}")
            header_parts.append(f"{'TID':<8}")
            if has_flush:
                header_parts.append(f"{'Flush(ms)':<12}")
            if has_log:
                header_parts.append(f"{'Log(ms)':<12}")
            if has_ctime:
                header_parts.append(f"{'Ctime(ms)':<12}")
            output.append(''.join(header_parts))
            output.append("    " + "-" * 50)
            
            # Show last 5 transactions
            for t in trans[-5:]:
                parts = ["    "]
                parts.append(f"{t.get('type', 'N/A'):<4}")
                parts.append(f"{t.get('tid', 'N/A'):<8}")
                if has_flush:
                    flush_val = t.get('flush_ms', 'N/A')
                    parts.append(f"{flush_val if flush_val != 'N/A' else 'N/A':<12}")
                if has_log:
                    log_val = t.get('log_ms', 'N/A')
                    parts.append(f"{log_val if log_val != 'N/A' else 'N/A':<12}")
                if has_ctime:
                    ctime_val = t.get('ctime_ms', 'N/A')
                    parts.append(f"{ctime_val if ctime_val != 'N/A' else 'N/A':<12}")
                output.append(''.join(parts))
            
            # Calculate averages
            flush_vals = [t['flush_ms'] for t in trans if 'flush_ms' in t and t['flush_ms'] is not None]
            log_vals = [t['log_ms'] for t in trans if 'log_ms' in t and t['log_ms'] is not None]
            ctime_vals = [t['ctime_ms'] for t in trans if 'ctime_ms' in t and t['ctime_ms'] is not None]
            
            if flush_vals:
                output.append(f"    Avg Flush: {sum(flush_vals)/len(flush_vals):.1f}ms")
            if log_vals:
                output.append(f"    Avg Log: {sum(log_vals)/len(log_vals):.1f}ms")
            if ctime_vals:
                output.append(f"    Avg Ctime: {sum(ctime_vals)/len(ctime_vals):.1f}ms")
        
        output.append("")
    
    return '\n'.join(output)

def print_xfs_stats(stats):
    """Print XFS statistics in a formatted way"""
    if not stats:
        return "  No XFS statistics available\n  (XFS may not be in use on this system)"
    
    output = []
    output.append("  XFS JOURNAL STATISTICS")
    output.append("  " + "-" * 70)
    
    # Log statistics
    output.append("  Log Operations:")
    if 'log_writes' in stats:
        output.append(f"    Log Writes: {stats['log_writes']:,}")
    if 'log_blocks' in stats:
        output.append(f"    Log Blocks: {stats['log_blocks']:,}")
    if 'log_force' in stats:
        output.append(f"    🔴 Log Forces: {stats['log_force']:,}  ← Flush events")
    if 'log_force_sleep' in stats:
        output.append(f"    Log Force Sleep: {stats['log_force_sleep']:,}")
    
    output.append("")
    
    # Flush daemon statistics
    output.append("  Flush Daemon (xstrat):")
    if 'xstrat_quick' in stats:
        output.append(f"    Quick Flushes: {stats['xstrat_quick']:,}")
    
    output.append("")
    
    # AIL flush statistics
    output.append("  AIL (Active Item List) Flushes:")
    if 'ail_push' in stats:
        output.append(f"    AIL Pushes: {stats['ail_push']:,}")
    if 'ail_push_flush' in stats:
        output.append(f"    AIL Flush Blocks: {stats['ail_push_flush']:,}")
    
    output.append("")
    
    # Extended precision stats (bytes)
    output.append("  Extended Precision (Bytes):")
    if 'flush_bytes' in stats:
        output.append(f"    🔴 Flush Bytes: {format_bytes(stats['flush_bytes'])}")
    if 'write_bytes' in stats:
        output.append(f"    Write Bytes: {format_bytes(stats['write_bytes'])}")
    if 'read_bytes' in stats:
        output.append(f"    Read Bytes: {format_bytes(stats['read_bytes'])}")
    
    output.append("")
    
    # Add legend
    output.append("  📖 Legend:")
    output.append("    🔴 = I/O flush/force operations (key metric for disk flushing)")
    
    return '\n'.join(output)

def get_journal_metrics_all():
    """
    Get journal metrics for both ext4 and XFS filesystems
    Returns a dictionary with both ext4 and XFS metrics
    """
    metrics = {}
    
    # Get ext4 metrics
    metrics['ext4'] = get_ext4_journal_stats()
    
    # Get XFS metrics
    metrics['xfs'] = get_xfs_stats()
    
    return metrics

def print_all_journal_metrics():
    """Print journal metrics for both ext4 and XFS"""
    metrics = get_journal_metrics_all()
    
    output = []
    output.append("╔" + "═" * 70 + "╗")
    output.append("║ JOURNAL (JBD2/XFS) STATISTICS " + " " * 38 + "║")
    output.append("╚" + "═" * 70 + "╝")
    output.append("")
    
    # Print ext4 stats
    output.append(print_ext4_journal_stats(metrics['ext4']))
    
    if metrics['ext4']:
        output.append("")
    
    # Print XFS stats
    output.append(print_xfs_stats(metrics['xfs']))
    
    return '\n'.join(output)

# Example usage
if __name__ == "__main__":
    print(print_all_journal_metrics())