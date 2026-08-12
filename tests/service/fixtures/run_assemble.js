"use strict";
/* The section 11 fixture runner: replay the recorded interaction
 * through the shipped page core and print the assembled record. */
const fs = require("fs");
const path = require("path");
const trial = require(path.join(__dirname, "..", "..", "..",
                                "service", "ui", "trial.js"));
const script = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const record = trial.assembleRecord(trial.applyScript(script));
process.stdout.write(JSON.stringify(record));
