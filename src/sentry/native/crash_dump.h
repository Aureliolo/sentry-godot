#pragma once

#include <map>
#include <string>

// A dump of the running process written by Crashpad's handler while the process goes on, as a
// game's stall watch asks for one when its main loop stops ticking. Kept apart from Godot's headers,
// since Crashpad's Windows headers bring in windows.h.
namespace sentry::native::crash_dump {

// Writes a minidump of every thread through the crash handler, without ending the process, into
// the database at p_database_path (UTF-8), where it waits as a crash's report does. Uploads are held
// while it is written, so the report is whole before the handler may take it up: consent given
// before the call is given again after it. Its event is a fresh one: its own event id (the report's
// id), level error, the scope as it stands now and p_tags over the scope's tags. Answers the new
// report's id, or empty where the handler wrote none (no handler running).
std::string write(const std::string &p_database_path, const std::map<std::string, std::string> &p_tags);

} //namespace sentry::native::crash_dump
