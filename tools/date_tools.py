# backend/tools/date_tools.py

from datetime import datetime, timedelta
from langchain_core.tools import tool
from zoneinfo import ZoneInfo

@tool
def get_current_date(timezone: str) -> str:
    """
    Get the current date and time in the user's timezone.
    
    Args:
        timezone: User's timezone (default: Asia/Kolkata)
    
    Returns:
        Current date and time in format: "Saturday, January 10, 2026 at 3:45 PM IST"
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        
        formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")
        tz_abbr = now.strftime("%Z")
        
        return f"{formatted} {tz_abbr}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_date_in_days(days: int, timezone: str ) -> str:
    """
    Calculate what date it will be N days from now.
    
    Args:
        days: Number of days from today (can be negative for past dates)
        timezone: User's timezone (default: Asia/Kolkata)
    
    Returns:
        Date in format: "Monday, January 15, 2026"
    
    Examples:
        get_date_in_days(7) → date 7 days from now
        get_date_in_days(-3) → date 3 days ago
    """
    try:
        tz = ZoneInfo(timezone)
        target_date = datetime.now(tz) + timedelta(days=days)
        
        return target_date.strftime("%A, %B %d, %Y")
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_next_weekday(weekday: str, timezone: str) -> str:
    """
    Find the date of the next occurrence of a specific weekday.
    
    Args:
        weekday: Day of week (Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday)
        timezone: User's timezone (default: Asia/Kolkata)
    
    Returns:
        Date in format: "Monday, January 15, 2026"
    
    Examples:
        get_next_weekday("Monday") → next Monday's date
        get_next_weekday("Friday") → next Friday's date
    """
    try:
        weekday_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        target_weekday = weekday_map.get(weekday.lower())
        if target_weekday is None:
            return f"Error: Invalid weekday '{weekday}'. Use Monday, Tuesday, etc."
        
        tz = ZoneInfo(timezone)
        today = datetime.now(tz)
        current_weekday = today.weekday()
        
        # Calculate days until target weekday
        days_ahead = target_weekday - current_weekday
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        
        target_date = today + timedelta(days=days_ahead)
        
        return target_date.strftime("%A, %B %d, %Y")
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def parse_relative_date(description: str, timezone: str) -> str:
    """
    Parse natural language date descriptions into actual dates.
    
    Args:
        description: Natural language like "tomorrow", "next week", "in 3 days", "back on 25th"
        timezone: User's timezone (default: Asia/Kolkata)
    
    Returns:
        Date in format: "Monday, January 15, 2026"
    
    Examples:
        parse_relative_date("tomorrow") → tomorrow's date
        parse_relative_date("next week") → date 7 days from now
        parse_relative_date("in 5 days") → date 5 days from now
        parse_relative_date("back on 25th") → January 25, 2026 (current month)
        parse_relative_date("summer 2026") -> June 1, 2026 
        parse_relative_date("by January 2027") -> January 1, 2027 
        
    """
    try:
        tz = ZoneInfo(timezone)
        today = datetime.now(tz)
        
        description = description.lower().strip()

        import re
        year_match = re.search(r'\b(20\d{2})\b', description)  # Matches 2024, 2025, 2026, etc.
        year = int(year_match.group(1)) if year_match else today.year
        
        # Handle common relative terms
        if description == "today":
            target_date = today
        elif description == "tomorrow":
            target_date = today + timedelta(days=1)
        elif description == "yesterday":
            target_date = today - timedelta(days=1)
        elif "next week" in description:
            target_date = today + timedelta(days=7)
        elif "next month" in description:
            if today.month == 12: 
                target_date = datetime(today.year + 1,1,1, tzinfo = tz)
            else: 
                target_date = datetime(today.year, today.month + 1, 1, tzinfo = tz)    
            # Approximate: add 30 days
        elif "summer" in description:
            target_date = datetime(year, 6, 1, tzinfo=tz)  # June 1st
        elif "fall" in description or "autumn" in description:
            target_date = datetime(year, 9, 1, tzinfo=tz)  # September 1st
        elif "winter" in description:
            target_date = datetime(year, 12, 1, tzinfo=tz)  # December 1st
        elif "spring" in description:
            target_date = datetime(year, 3, 1, tzinfo=tz)  # March 1st
        
        # Handle month names with year
        elif any(month in description for month in ['january', 'february', 'march', 'april', 'may', 'june',
                                                      'july', 'august', 'september', 'october', 'november', 'december']):
            month_map = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
                'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
            }
            for month_name, month_num in month_map.items():
                if month_name in description:
                    # Extract day if mentioned, default to 1st
                    day_match = re.search(r'\b(\d{1,2})\b', description)
                    day = int(day_match.group(1)) if day_match else 1
                    target_date = datetime(year, month_num, day, tzinfo=tz)
                    break
        
        # Handle "in X days/weeks/months"
        elif "in" in description and ("day" in description or "week" in description or "month" in description):
            match = re.search(r'(\d+)', description)
            if match:
                num = int(match.group(1))
                if "week" in description:
                    target_date = today + timedelta(days=num * 7)
                elif "month" in description:
                    target_date = today + timedelta(days=num * 30)
                else:  # days
                    target_date = today + timedelta(days=num)
            else:
                return "Error: Could not parse number"
        
        # Handle "on the 25th" (with or without month)
        elif "on" in description or "the" in description:
            day_match = re.search(r'\b(\d{1,2})(st|nd|rd|th)?\b', description)
            if day_match:
                day = int(day_match.group(1))
                # Use specified year, or current year
                target_date = datetime(year, today.month, day, tzinfo=tz)
                
                # If date already passed this month and no year specified, assume next month
                if target_date < today and not year_match:
                    if today.month == 12:
                        target_date = datetime(today.year + 1, 1, day, tzinfo=tz)
                    else:
                        target_date = datetime(today.year, today.month + 1, day, tzinfo=tz)
            else:
                return "Error: Could not parse day number"
        
        else:
            return f"Error: Could not parse '{description}'. Try 'tomorrow', 'in X days', 'summer 2026', or 'January 15, 2027'"
        
        return target_date.strftime("%A, %B %d, %Y")
    
    except Exception as e:
        return f"Error: {str(e)}"    

@tool
def calculate_days_between(from_date: str, to_date: str, timezone: str) -> str:
    """
    Calculate number of days between two dates.
    
    Args:
        from_date: Start date in format "YYYY-MM-DD" or "January 15, 2026"
        to_date: End date in format "YYYY-MM-DD" or "January 15, 2026"
        timezone: User's timezone (default: Asia/Kolkata)
    
    Returns:
        Number of days between dates
    
    Examples:
        calculate_days_between("2026-01-10", "2026-01-15") → "5 days"
    """
    try:
        from dateutil import parser
        
        tz = ZoneInfo(timezone)
        
        # Parse both dates
        date1 = parser.parse(from_date).replace(tzinfo=tz)
        date2 = parser.parse(to_date).replace(tzinfo=tz)
        
        # Calculate difference
        delta = abs((date2 - date1).days)
        
        return f"{delta} days"
    except Exception as e:
        return f"Error parsing dates: {str(e)}"