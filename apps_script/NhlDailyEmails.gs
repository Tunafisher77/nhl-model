var NHL_GAME_TAB = 'NHL Game Email Summary';
var NHL_GOAL_TAB = 'NHL Goal Scorer Email Summary';
var NHL_CARD_TAB = 'NHL Best Card Email Summary';
var NHL_TZ = 'America/Los_Angeles';

function sendDailyNhlEmailsIfFresh() {
  sendNhlTableIfFresh_(NHL_GAME_TAB, 'Daily NHL Game Picks', 'nhl_game');
  sendNhlTableIfFresh_(NHL_GOAL_TAB, 'Daily NHL Goal Scorer Picks', 'nhl_goal');
  sendNhlTableIfFresh_(NHL_CARD_TAB, 'Daily NHL Best Cards', 'nhl_card');
}

function sendNhlGameEmailIfFresh() { sendNhlTableIfFresh_(NHL_GAME_TAB, 'Daily NHL Game Picks', 'nhl_game'); }
function sendNhlGoalEmailIfFresh() { sendNhlTableIfFresh_(NHL_GOAL_TAB, 'Daily NHL Goal Scorer Picks', 'nhl_goal'); }
function sendNhlBestCardEmailIfFresh() { sendNhlTableIfFresh_(NHL_CARD_TAB, 'Daily NHL Best Cards', 'nhl_card'); }

function sendNhlTestEmails() {
  sendNhlTestTable_(NHL_GAME_TAB, '[TEST] Daily NHL Game Picks');
  sendNhlTestTable_(NHL_GOAL_TAB, '[TEST] Daily NHL Goal Scorer Picks');
  sendNhlTestTable_(NHL_CARD_TAB, '[TEST] Daily NHL Best Cards');
}

function sendNhlTestTable_(tabName, subjectPrefix) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(tabName);
  if (!sheet || sheet.getLastRow() < 2) throw new Error(tabName + ' has no test data.');
  var data = sheet.getDataRange().getDisplayValues();
  var runDate = data[1][0];
  var props = PropertiesService.getScriptProperties();
  var recipient = props.getProperty('NHL_EMAIL_TO') || Session.getEffectiveUser().getEmail();
  if (!recipient) throw new Error('Set Script Property NHL_EMAIL_TO to the delivery email address.');
  GmailApp.sendEmail(recipient, subjectPrefix + ' - ' + runDate,
    'Open this email in HTML view.', {htmlBody: buildNhlEmailHtml_(subjectPrefix, runDate, data)});
}

function sendNhlTableIfFresh_(tabName, subjectPrefix, markerPrefix) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(tabName);
  if (!sheet || sheet.getLastRow() < 2) return;
  var data = sheet.getDataRange().getDisplayValues();
  var runDate = data[1][0];
  var today = Utilities.formatDate(new Date(), NHL_TZ, 'yyyy-MM-dd');
  if (runDate !== today) return;
  for (var i = 2; i < data.length; i++) {
    if (data[i][0] !== runDate) throw new Error(tabName + ' contains mixed run dates');
  }
  var props = PropertiesService.getScriptProperties();
  var marker = markerPrefix + '_sent_' + runDate;
  if (props.getProperty(marker)) return;
  var recipient = props.getProperty('NHL_EMAIL_TO') || Session.getEffectiveUser().getEmail();
  if (!recipient) throw new Error('Set Script Property NHL_EMAIL_TO to the delivery email address.');
  var html = buildNhlEmailHtml_(subjectPrefix, runDate, data);
  GmailApp.sendEmail(recipient, subjectPrefix + ' - ' + runDate, 'Open this email in HTML view.', {htmlBody: html});
  props.setProperty(marker, new Date().toISOString());
}

function buildNhlEmailHtml_(title, runDate, data) {
  var html = '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111;line-height:1.45">' +
    '<h2>' + escapeNhl_(title) + '</h2>' +
    '<p><strong>Slate Date:</strong> ' + escapeNhl_(runDate) + '</p>';
  var headers = data[0];
  var rows = data.slice(1).map(function(row) { return nhlRowObject_(headers, row); });
  if (title.indexOf('Best Card') !== -1 || title.indexOf('Best Cards') !== -1) {
    html += buildNhlBestCards_(rows);
  } else if (title.indexOf('Goal Scorer') !== -1) {
    html += buildNhlGoalScorers_(rows);
  } else {
    html += buildNhlGames_(rows);
  }
  return html + '<p style="color:#666;font-size:12px;margin-top:24px">' +
    'Statistics-only selections. No sportsbook odds, lines, implied probabilities, or market influence are used.' +
    '</p></div>';
}

function nhlRowObject_(headers, row) {
  var obj = {};
  headers.forEach(function(header, index) { obj[header] = row[index] || ''; });
  return obj;
}

function buildNhlGames_(rows) {
  var html = '<h3>Daily Outlook</h3><p>' + rows.length +
    ' regular-season games evaluated using team strength, goal differential, recent form, and home ice.</p>';
  rows.forEach(function(row) {
    html += '<br><h3>' + escapeNhl_(row.Matchup) + '</h3>' +
      '<p><strong>Projected Winner:</strong> ' + escapeNhl_(row.Pick) + '<br>' +
      '<strong>Win Probability:</strong> ' + escapeNhl_(row['Win Probability']) + '%<br>' +
      '<strong>Confidence:</strong> ' + escapeNhl_(row.Confidence) + '<br>' +
      '<strong>Game Time:</strong> ' + escapeNhl_(row['Start UTC']) + '<br>' +
      '<strong>Why Today:</strong> ' + escapeNhl_(row.Reason) + '</p>';
  });
  return html;
}

function buildNhlGoalScorers_(rows) {
  var html = '<h3>Top Goal Scorer Picks</h3>';
  rows.forEach(function(row, index) {
    html += '<p><strong>' + (index + 1) + '. ' + escapeNhl_(row.Player) +
      ' (' + escapeNhl_(row.Team) + ')</strong><br>' +
      '<strong>Matchup:</strong> ' + escapeNhl_(row.Matchup) + '<br>' +
      '<strong>Goal Score:</strong> ' + escapeNhl_(row['Goal Score']) + '<br>' +
      '<strong>Goals/Game:</strong> ' + escapeNhl_(row['Goal Rate']) + '<br>' +
      '<strong>Shots/Game:</strong> ' + escapeNhl_(row['Shots/Game']) + '<br>' +
      '<strong>Confidence:</strong> ' + escapeNhl_(row.Confidence) + '</p>';
  });
  return html;
}

function buildNhlBestCards_(rows) {
  var cards = {};
  rows.forEach(function(row) {
    if (!cards[row.Card]) cards[row.Card] = [];
    cards[row.Card].push(row);
  });
  var html = '';
  Object.keys(cards).sort(function(a, b) { return Number(a) - Number(b); }).forEach(function(card) {
    var picks = cards[card];
    html += '<br><h3>Card ' + escapeNhl_(card) + ' — ' + escapeNhl_(picks[0].Matchup) + '</h3>';
    picks.forEach(function(pick) {
      html += '<p><strong>' + escapeNhl_(pick['Pick Type']) + ':</strong> ' +
        escapeNhl_(pick.Selection);
      if (pick.Team && pick.Team !== pick.Selection) html += ' (' + escapeNhl_(pick.Team) + ')';
      if (pick['Model Score']) html += '<br><strong>Model Score:</strong> ' + escapeNhl_(pick['Model Score']);
      html += '<br><strong>Confidence:</strong> ' + escapeNhl_(pick.Confidence) + '</p>';
    });
  });
  html += '<h3>Model Notes</h3><p>Each card contains one projected game winner, one goal scorer from each team, two assist candidates, and two shots-on-goal candidates.</p>';
  return html;
}

function escapeNhl_(value) {
  return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function installNhlEmailTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'sendDailyNhlEmailsIfFresh') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('sendDailyNhlEmailsIfFresh').timeBased().everyHours(1).create();
}
