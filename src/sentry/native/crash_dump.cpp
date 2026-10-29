#include "crash_dump.h"

#include "crash_database.h"

// sentry-native's own headers, not its public API: the event a crash's report carries is built in
// its Crashpad backend from the scope, which the public API never hands out, and on Linux that
// backend writes it only from inside a crash. The pinned submodule fixes these.
extern "C" {
#include "sentry_boot.h"

#include "sentry_core.h"
#include "sentry_options.h"
#include "sentry_path.h"
#include "sentry_scope.h"
#include "sentry_utils.h"
#include "sentry_value.h"
}

#include "client/simulate_crash.h"

#include <set>

namespace {

std::set<std::string> _ids(const std::string &p_database_path) {
	std::set<std::string> ids;
	for (const sentry::native::crash_database::PendingReport &report : sentry::native::crash_database::pending_reports(p_database_path)) {
		ids.insert(report.id);
	}
	return ids;
}

// The newest waiting report not among p_before: the one the handler just wrote.
std::string _new_id(const std::string &p_database_path, const std::set<std::string> &p_before) {
	std::string found;
	int64_t newest = -1;
	for (const sentry::native::crash_database::PendingReport &report : sentry::native::crash_database::pending_reports(p_database_path)) {
		if (p_before.count(report.id) == 0 && report.created > newest) {
			newest = report.created;
			found = report.id;
		}
	}
	return found;
}

// What the backend writes as a crash's __sentry-event, with this report's own id: the backend's
// carries one id for the whole run, and Sentry keeps only the first event of an id, so a crash
// after the dump, or a second dump, would be dropped as a duplicate.
sentry_value_t _event(const std::string &p_id, const std::map<std::string, std::string> &p_tags) {
	sentry_value_t event = sentry_value_new_object();
	sentry_uuid_t uuid = sentry_uuid_from_string(p_id.c_str());
	sentry_value_set_by_key(event, "event_id", sentry__value_new_uuid(&uuid));
	sentry_value_set_by_key(event, "level", sentry__value_new_level(SENTRY_LEVEL_ERROR));
	sentry_value_set_by_key(event, "timestamp", sentry__value_new_string_owned(sentry__usec_time_to_iso8601(sentry__usec_time())));
	SENTRY_WITH_OPTIONS (options) {
		SENTRY_WITH_SCOPE (scope) {
			sentry__scope_apply_to_event(scope, options, event, SENTRY_SCOPE_NONE);
		}
	}
	sentry_value_t found = sentry_value_get_by_key(event, "tags");
	sentry_value_t tags = sentry_value_is_null(found) ? sentry_value_new_object() : sentry__value_clone(found);
	for (const auto &tag : p_tags) {
		sentry_value_set_by_key(tags, tag.first.c_str(), sentry_value_new_string(tag.second.c_str()));
	}
	sentry_value_set_by_key(event, "tags", tags);
	return event;
}

bool _write_event(const std::string &p_database_path, const std::string &p_id, sentry_value_t p_event) {
	size_t size = 0;
	char *packed = sentry_value_to_msgpack(p_event, &size);
	if (packed == nullptr) {
		return false;
	}
	bool written = false;
	sentry_path_t *database = sentry__path_from_str(p_database_path.c_str());
	sentry_path_t *attachments = database ? sentry__path_join_str(database, "attachments") : nullptr;
	sentry_path_t *folder = attachments ? sentry__path_join_str(attachments, p_id.c_str()) : nullptr;
	sentry_path_t *file = folder ? sentry__path_join_str(folder, "__sentry-event") : nullptr;
	if (file != nullptr && sentry__path_create_dir_all(folder) == 0) {
		written = sentry__path_write_buffer(file, packed, size) == 0;
	}
	sentry__path_free(file);
	sentry__path_free(folder);
	sentry__path_free(attachments);
	sentry__path_free(database);
	sentry_free(packed);
	return written;
}

} // unnamed namespace

namespace sentry::native::crash_dump {

std::string write(const std::string &p_database_path, const std::map<std::string, std::string> &p_tags) {
	const std::set<std::string> before = _ids(p_database_path);
	const sentry_user_consent_t held = sentry_user_consent_get();
	if (held == SENTRY_USER_CONSENT_GIVEN) {
		sentry_user_consent_reset();
	}
	// Returns once the handler has written the report: it suspends every thread, this one waiting
	// on it, and records each one's stack.
	CRASHPAD_SIMULATE_CRASH();
	const std::string id = _new_id(p_database_path, before);
	if (!id.empty()) {
		sentry_value_t event = _event(id, p_tags);
		_write_event(p_database_path, id, event);
		sentry_value_decref(event);
	}
	if (held == SENTRY_USER_CONSENT_GIVEN) {
		sentry_user_consent_give();
	}
	return id;
}

} //namespace sentry::native::crash_dump
