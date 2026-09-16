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
  var html = '<div style="font-family:Arial,sans-serif;max-width:1000px;margin:auto">' +
    '<h2 style="color:#163a63">' + escapeNhl_(title) + '</h2><p><b>' + escapeNhl_(runDate) + '</b></p>' +
    '<table style="border-collapse:collapse;width:100%;font-size:13px"><thead><tr>';
  data[0].forEach(function(v) { html += '<th style="background:#163a63;color:white;padding:8px;border:1px solid #ccc">' + escapeNhl_(v) + '</th>'; });
  html += '</tr></thead><tbody>';
  for (var r = 1; r < data.length; r++) {
    html += '<tr style="background:' + (r % 2 ? '#f4f7fb' : '#fff') + '">';
    data[r].forEach(function(v) { html += '<td style="padding:7px;border:1px solid #ccc">' + escapeNhl_(v) + '</td>'; });
    html += '</tr>';
  }
  return html + '</tbody></table><p style="color:#666;font-size:11px">Statistics-only model; no betting lines.</p></div>';
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
