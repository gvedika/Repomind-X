const LEVELS = ["debug", "info", "warn", "error"];

function format(level, message, fields) {
  return JSON.stringify({ level, message, time: new Date().toISOString(), ...fields });
}

export const logger = Object.fromEntries(
  LEVELS.map((level) => [level, (message, fields = {}) => console.log(format(level, message, fields))])
);
