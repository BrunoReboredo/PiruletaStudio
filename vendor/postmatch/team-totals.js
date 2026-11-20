/* Sum all source players, including substitutes outside the visible columns. */
(function (root) {
  function total(players, authoritativeTeams, team, key) {
    const rows = players.filter(player => player && player.TeamNum === team);
    const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    if (rows.length && rows.every(player => valid(player[key]))) {
      return rows.reduce((sum, player) => sum + player[key], 0);
    }
    const fallback = authoritativeTeams?.[team]?.[key];
    return valid(fallback) ? fallback : null;
  }
  root.PiruletaTeamTotals = {total};
  if (typeof module !== 'undefined' && module.exports) module.exports = {total};
})(typeof globalThis !== 'undefined' ? globalThis : this);
