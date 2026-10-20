"""Retrieval metrics keep unanswerable and abstaining cases out of precision denominators."""
def unique(ids):return list(dict.fromkeys(ids))

def recall_at_k(ids,relevant,k):
    if not relevant:return None
    return len(set(unique(ids)[:k])&set(relevant))/len(set(relevant))

def mrr_at_k(ids,relevant,k):
    if not relevant:return None
    return next((1/(index+1) for index,id in enumerate(unique(ids)[:k]) if id in relevant),0.0)

def faithfulness(supported):
    return sum(bool(value) for value in supported)/len(supported) if supported else None
