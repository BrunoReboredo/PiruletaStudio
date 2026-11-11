"""Player identity and roster merging for full and partial spectator packets."""
import json


def player_key(player):
    name = str(player.get('Name') or '')
    team = player.get('TeamNum', 0)
    primary = player.get('PrimaryId')
    if primary and name:
        # Some clients/bots share a PrimaryId. A name must remain part of the key.
        return json.dumps([primary, name, team], ensure_ascii=False, sort_keys=True)
    return json.dumps([team, name or player.get('Shortcut', '')], ensure_ascii=False)


def normalize_player(player):
    if not isinstance(player, dict) or not player.get('Name') or player.get('bSpectator'):
        return None
    # The game's serializer can omit fields whose value is zero, including blue TeamNum.
    try:
        team = int(player.get('TeamNum', 0))
    except (ValueError, TypeError):
        return None
    if team not in (0, 1):
        return None
    return {**player, 'Name': str(player['Name']), 'TeamNum': team}


def merge_players(*groups):
    result = []
    for group in groups:
        for source in group:
            player = normalize_player(source)
            if player is None:
                continue
            # Event payloads often omit PrimaryId, so match the name and game side too.
            existing = next((p for p in result if p['Name'] == player['Name'] and p['TeamNum'] == player['TeamNum']), None)
            if existing is None:
                result.append(dict(player))
            else:
                existing.update(player)
    return result
