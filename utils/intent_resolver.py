# utils/intent_resolver.py
"""
Intent Resolution Layer
Translates natural language → exact Firebase entity names
This runs BEFORE any tool is called
"""

from utils.firebase_client import FirebaseClient
from difflib import SequenceMatcher
from typing import Optional, Dict, List

class IntentResolver:
    """
    Resolves user's natural language references to exact Firebase entities.
    
    Examples:
    - "30 pounds shoulder" → "Shoulder Press 30lbs" (task name)
    - "workout stuff" → "Health" (folder name)
    - "woke up at 5:45" → "Wake up at 5:45 AM" (task name)
    """
    
    def __init__(self):
        self.client = FirebaseClient()
        self._task_cache = None
        self._folder_cache = None
    
    def resolve_task_name(self, user_input: str, only_incomplete: bool = False, user_id: str = None) -> Optional[Dict]:
        """
        Find the actual task name from user's natural language.
        
        Args:
            user_input: How user describes the task
            only_incomplete: If True, only search incomplete tasks (for mark complete)
                           If False, search ALL tasks (default)
            user_id: Firebase UID of the user
        
        Returns:
            {
                'exact_name': 'Wake up at 5:45 AM',
                'confidence': 0.85,
                'id': 'task_123',
                'folder': 'everyday_to_dos',
                'completed': False
            }
            or None if no match
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        # Get all tasks for this user
        tasks = self.client.get_all_tasks(user_id)
        
        # Filter to incomplete only if requested
        if only_incomplete:
            tasks = [t for t in tasks if not t.get('completed', False)]
        
        if not tasks:
            return None
        
        # Find best match
        best_match = self._fuzzy_match(
            user_input,
            tasks,
            key_field='name'
        )
        
        return best_match
    
    def resolve_folder_name(self, user_input: str, user_id: str = None) -> Optional[Dict]:
        """
        Find the actual folder name from user's natural language.
        
        Args:
            user_input: How user describes the folder
            user_id: Firebase UID of the user
        
        Returns:
            {
                'exact_name': 'Health',
                'confidence': 0.9,
                'id': 'health',
                'emoji': '💪'
            }
            or None if no match
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        # Get all folders for this user
        folders = []
        try:
            folder_docs = self.client._get_user_folders_ref(user_id).stream()
            for doc in folder_docs:
                data = doc.to_dict()
                folders.append({
                    'id': doc.id,
                    'name': data['name'],
                    'emoji': data.get('emoji', '')
                })
        except Exception as e:
            print(f"Error fetching folders: {e}")
            return None
        
        if not folders:
            return None
        
        # Find best match
        best_match = self._fuzzy_match(
            user_input,
            folders,
            key_field='name'
        )
        
        return best_match
    
    def _fuzzy_match(
        self,
        user_input: str,
        candidates: List[Dict],
        key_field: str,
        threshold: float = 0.4
    ) -> Optional[Dict]:
        """
        Core fuzzy matching algorithm.
        
        Returns the best matching candidate with confidence score.
        """
        if not candidates:
            return None
        
        user_lower = user_input.lower().strip()
        user_words = set(user_lower.split())
        
        best_candidate = None
        best_score = 0.0
        
        for candidate in candidates:
            candidate_text = candidate.get(key_field, '').lower()
            candidate_words = set(candidate_text.split())
            
            # Scoring algorithm
            score = 0.0
            
            # 1. Exact substring match (highest priority)
            if user_lower in candidate_text:
                score = 0.95
            elif candidate_text in user_lower:
                score = 0.90
            else:
                # 2. Fuzzy string similarity (Levenshtein-based)
                fuzzy_score = SequenceMatcher(None, user_lower, candidate_text).ratio()
                
                # 3. Keyword overlap
                word_overlap = len(user_words & candidate_words)
                if word_overlap > 0:
                    keyword_score = word_overlap / max(len(user_words), len(candidate_words))
                    # Boost keyword score
                    keyword_score *= 0.85
                else:
                    keyword_score = 0.0
                
                # 4. Partial word matching (e.g., "shoulder" matches "shoulder press")
                partial_matches = sum(
                    1 for u_word in user_words
                    for c_word in candidate_words
                    if u_word in c_word or c_word in u_word
                )
                partial_score = partial_matches / max(len(user_words), len(candidate_words)) * 0.7
                
                # Take the best score
                score = max(fuzzy_score, keyword_score, partial_score)
            
            # Update best match
            if score > best_score:
                best_score = score
                best_candidate = candidate
        
        # Only return if above threshold
        if best_score >= threshold:
            return {
                **best_candidate,
                'exact_name': best_candidate[key_field],
                'confidence': best_score
            }
        
        return None
    
    def get_task_suggestions(self, user_input: str, limit: int = 5, only_incomplete: bool = False, user_id: str = None) -> List[Dict]:
        """
        Get list of possible task matches for disambiguation.
        
        Args:
            user_input: User's description
            limit: Max suggestions to return
            only_incomplete: If True, only suggest incomplete tasks
            user_id: Firebase UID of the user
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        tasks = self.client.get_all_tasks(user_id)
        
        # Filter if needed
        if only_incomplete:
            tasks = [t for t in tasks if not t.get('completed', False)]
        
        user_lower = user_input.lower()
        scored_tasks = []
        
        for task in tasks:
            task_name = task.get('name', '').lower()
            score = SequenceMatcher(None, user_lower, task_name).ratio()
            
            if score > 0.2:  # Low threshold for suggestions
                scored_tasks.append({
                    'name': task['name'],
                    'folder': task.get('folder', ''),
                    'completed': task.get('completed', False),
                    'score': score
                })
        
        # Sort by score and return top N
        scored_tasks.sort(key=lambda x: x['score'], reverse=True)
        return scored_tasks[:limit]
    
    def get_folder_suggestions(self, user_input: str, limit: int = 5, user_id: str = None) -> List[Dict]:
        """Get list of possible folder matches for disambiguation"""
        if not user_id:
            raise ValueError("user_id is required")
        
        folders = []
        folder_docs = self.client._get_user_folders_ref(user_id).stream()
        
        for doc in folder_docs:
            data = doc.to_dict()
            folders.append({
                'name': data['name'],
                'emoji': data.get('emoji', ''),
                'id': doc.id
            })
        
        user_lower = user_input.lower()
        scored_folders = []
        
        for folder in folders:
            folder_name = folder['name'].lower()
            score = SequenceMatcher(None, user_lower, folder_name).ratio()
            
            if score > 0.2:
                scored_folders.append({
                    **folder,
                    'score': score
                })
        
        scored_folders.sort(key=lambda x: x['score'], reverse=True)
        return scored_folders[:limit]


# ============================================
# Global instance
# ============================================
intent_resolver = IntentResolver()