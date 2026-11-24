def inspect_user_votes(user_row, u_votes, expected_carafes, expected_wine_ids):
    expected_count = len(expected_carafes)
    filtered = [
        v for v in u_votes
        if v['carafe_number'] in expected_carafes and v['guessed_wine_id'] in expected_wine_ids
    ]
    valid_carafes = {v['carafe_number'] for v in filtered}
    valid_guessed_wines = {v['guessed_wine_id'] for v in filtered}
    saved_count = len(valid_carafes)

    has_complete_unique_votes = (
        expected_count > 0
        and len(filtered) == expected_count
        and len(valid_carafes) == expected_count
        and len(valid_guessed_wines) == expected_count
    )
    is_validated = bool(user_row['votes_submitted']) and has_complete_unique_votes
    return is_validated, saved_count


def get_pending_voters(db):
    users = db.execute('SELECT id, username, votes_submitted FROM users ORDER BY username').fetchall()
    wines = db.execute('SELECT id, carafe_number FROM wines WHERE carafe_number IS NOT NULL').fetchall()
    expected_carafes = {w['carafe_number'] for w in wines}
    expected_wine_ids = {w['id'] for w in wines}
    expected_count = len(expected_carafes)

    if not users or expected_count == 0:
        return [], expected_count

    votes = db.execute('SELECT user_id, carafe_number, guessed_wine_id FROM votes').fetchall()
    votes_by_user = {}
    for v in votes:
        votes_by_user.setdefault(v['user_id'], []).append(v)

    pending = []
    for u in users:
        u_votes = votes_by_user.get(u['id'], [])
        is_validated, saved_count = inspect_user_votes(u, u_votes, expected_carafes, expected_wine_ids)
        if not is_validated:
            pending.append({
                'id': u['id'],
                'username': u['username'],
                'voted_count': saved_count,
                'expected_count': expected_count
            })

    return pending, expected_count


def compute_results_data(db, uid=None):
    wines = db.execute('SELECT * FROM wines WHERE carafe_number IS NOT NULL ORDER BY carafe_number').fetchall()
    users = db.execute('SELECT * FROM users ORDER BY username').fetchall()
    votes = db.execute('SELECT * FROM votes').fetchall()
    notes = db.execute('SELECT * FROM notes').fetchall()

    wine_by_id = {w['id']: w for w in wines}
    votes_lookup = {(v['user_id'], v['carafe_number']): v['guessed_wine_id'] for v in votes}
    user_votes_by_wine = {
        v['guessed_wine_id']: v['carafe_number']
        for v in votes
        if uid is not None and v['user_id'] == uid and v['guessed_wine_id']
    }
    my_notes_by_wine = {
        n['wine_id']: dict(n)
        for n in notes
        if uid is not None and n['user_id'] == uid
    }

    total_players = len(users)
    total_wines = len(wines)

    correct_counts_by_carafe = {}
    weight_by_carafe = {}
    for w in wines:
        c_num = w['carafe_number']
        c_count = sum(1 for u in users if votes_lookup.get((u['id'], c_num)) == w['id'])
        correct_counts_by_carafe[c_num] = c_count
        if total_players > 0 and c_count > 0:
            weight_by_carafe[c_num] = round(total_players / c_count, 2)
        else:
            weight_by_carafe[c_num] = 0.0

    leaderboard = []
    for u in users:
        score = 0
        weighted_score = 0.0
        best_single_weight = 0.0
        best_single_wine_name = None

        for w in wines:
            c_num = w['carafe_number']
            if votes_lookup.get((u['id'], c_num)) == w['id']:
                score += 1
                w_pts = weight_by_carafe[c_num]
                weighted_score += w_pts
                if w_pts > best_single_weight:
                    best_single_weight = w_pts
                    best_single_wine_name = w['name']

        user_ratings = [n['rating'] for n in notes if n['user_id'] == u['id'] and n['rating'] is not None]
        avg_given_rating = round(sum(user_ratings) / len(user_ratings), 1) if user_ratings else None

        leaderboard.append({
            'user_id': u['id'],
            'username': u['username'],
            'score': score,
            'weighted_score': round(weighted_score, 2),
            'total': total_wines,
            'is_me': (uid is not None and u['id'] == uid),
            'best_single_weight': best_single_weight,
            'best_single_wine_name': best_single_wine_name,
            'avg_given_rating': avg_given_rating
        })

    leaderboard.sort(key=lambda x: (-x['score'], -x['weighted_score'], x['username'].lower()))
    for idx, entry in enumerate(leaderboard, start=1):
        entry['rank'] = idx

    carafe_details = []
    wine_stats = []
    my_notes_review = []

    for w in wines:
        carafe_num = w['carafe_number']
        correct_count = correct_counts_by_carafe[carafe_num]
        weight = weight_by_carafe[carafe_num]
        success_rate = round((correct_count / total_players) * 100) if total_players > 0 else 0

        wine_notes = [n['rating'] for n in notes if n['wine_id'] == w['id'] and n['rating'] is not None]
        avg_rating = round(sum(wine_notes) / len(wine_notes), 1) if wine_notes else None

        player_guesses = []
        for u in users:
            guessed_id = votes_lookup.get((u['id'], carafe_num))
            guessed_wine = wine_by_id.get(guessed_id)
            if guessed_wine:
                is_correct = (guessed_id == w['id'])
                player_guesses.append({
                    'username': u['username'],
                    'guessed_name': guessed_wine['name'],
                    'guessed_year': guessed_wine['year'],
                    'status': 'correct' if is_correct else 'wrong',
                    'is_me': (u['id'] == uid)
                })
            else:
                player_guesses.append({
                    'username': u['username'],
                    'guessed_name': 'Aucun vote',
                    'guessed_year': '',
                    'status': 'missing',
                    'is_me': (u['id'] == uid)
                })

        carafe_details.append({
            'carafe_number': carafe_num,
            'actual_wine': w,
            'guesses': player_guesses,
            'correct_count': correct_count,
            'total_players': total_players,
            'success_rate': success_rate,
            'weight': weight
        })

        wine_stats.append({
            'carafe_number': carafe_num,
            'name': w['name'],
            'year': w['year'],
            'correct_count': correct_count,
            'total_players': total_players,
            'success_rate': success_rate,
            'weight': weight,
            'avg_rating': avg_rating
        })

        guessed_carafe_for_this_wine = user_votes_by_wine.get(w['id'])
        my_notes_review.append({
            'wine': w,
            'note': my_notes_by_wine.get(w['id'], {}),
            'guessed_carafe': guessed_carafe_for_this_wine,
            'found_it': (guessed_carafe_for_this_wine == carafe_num)
        })

    hardest_wine = min(wine_stats, key=lambda x: (x['correct_count'], -x['carafe_number'])) if wine_stats else None
    easiest_wine = max(wine_stats, key=lambda x: (x['correct_count'], -x['carafe_number'])) if wine_stats else None

    poker_candidates = [p for p in leaderboard if p['best_single_weight'] > 0]
    poker_winner = max(
        poker_candidates,
        key=lambda x: (x['best_single_weight'], x['weighted_score'])
    ) if poker_candidates else None

    raters = [p for p in leaderboard if p['avg_given_rating'] is not None]
    most_generous = max(raters, key=lambda x: x['avg_given_rating']) if raters else None
    most_strict = min(raters, key=lambda x: x['avg_given_rating']) if raters else None

    rated_wines = [ws for ws in wine_stats if ws['avg_rating'] is not None]
    surprise_trap = max(
        rated_wines,
        key=lambda x: (x['avg_rating'] - (x['success_rate'] / 10.0))
    ) if rated_wines else None

    fun_stats = {
        'poker_winner': poker_winner,
        'most_generous': most_generous,
        'most_strict': most_strict,
        'surprise_trap': surprise_trap
    }

    total_possible_votes = total_players * total_wines
    total_correct_votes = sum(x['correct_count'] for x in wine_stats)
    global_success_rate = round((total_correct_votes / total_possible_votes) * 100) if total_possible_votes > 0 else 0

    stats = {
        'total_players': total_players,
        'total_wines': total_wines,
        'global_success_rate': global_success_rate,
        'total_correct_votes': total_correct_votes,
        'total_possible_votes': total_possible_votes,
        'hardest_wine': hardest_wine,
        'easiest_wine': easiest_wine,
        'fun_stats': fun_stats
    }

    return wines, leaderboard, carafe_details, wine_stats, stats, my_notes_review