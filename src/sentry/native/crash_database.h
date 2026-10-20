#pragma once

#include <cstdint>
#include <string>
#include <vector>

// Crash reports Crashpad holds in its database while user consent is required and not given.
// Kept apart from Godot's headers, since Crashpad's Windows headers bring in windows.h.
namespace sentry::native::crash_database {

struct PendingReport {
	std::string id;
	// When the crash was written, in Unix seconds.
	int64_t created = 0;
};

// The reports still waiting to be uploaded in the database at p_database_path (UTF-8).
std::vector<PendingReport> pending_reports(const std::string &p_database_path);

// Deletes every waiting report with its attachments; answers how many were deleted.
int delete_pending_reports(const std::string &p_database_path);

} //namespace sentry::native::crash_database
