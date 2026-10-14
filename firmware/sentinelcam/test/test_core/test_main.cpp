#include <unity.h>
#include <string>
#include <vector>
#include "bcs_core.h"

void setUp() {}
void tearDown() {}

void test_double_reset_opens_portal() { TEST_ASSERT(drd_on_boot(true) == DrdDecision::OpenPortal); TEST_ASSERT(drd_on_boot(false) == DrdDecision::Normal); }
void test_flag_cleared_after_5s() { TEST_ASSERT_FALSE(drd_should_clear(4999)); TEST_ASSERT_TRUE(drd_should_clear(5000)); }
void test_netlist_dedupes_and_caps_at_5() {
  std::vector<Net> l; for (int i = 0; i < 6; i++) l = netlist_add(l, {"n" + std::to_string(i), "p"});
  TEST_ASSERT_EQUAL(5, l.size()); TEST_ASSERT_EQUAL_STRING("n5", l[0].ssid.c_str());
  l = netlist_add(l, {"n3", "new"}); TEST_ASSERT_EQUAL(5, l.size()); TEST_ASSERT_EQUAL_STRING("new", l[0].pass.c_str());
}
void test_auth_accepts_bearer_or_query_only_when_equal() {
  TEST_ASSERT_TRUE(auth_ok("Bearer abc", nullptr, "abc")); TEST_ASSERT_TRUE(auth_ok(nullptr, "abc", "abc"));
  TEST_ASSERT_FALSE(auth_ok("Bearer abd", nullptr, "abc")); TEST_ASSERT_FALSE(auth_ok(nullptr, nullptr, "abc"));
}
void test_auth_rejects_length_mismatch_and_empty() {
  TEST_ASSERT_FALSE(auth_ok("Bearer abcd", nullptr, "abc")); TEST_ASSERT_FALSE(auth_ok("Bearer ab", nullptr, "abc"));
  TEST_ASSERT_FALSE(auth_ok("abc", nullptr, "abc")); TEST_ASSERT_FALSE(auth_ok("Bearer ", nullptr, ""));
  TEST_ASSERT_FALSE(auth_ok(nullptr, "", "")); TEST_ASSERT_FALSE(auth_ok("Bearer abc", nullptr, nullptr));
}
void test_int_in_range_checks_bounds_before_cast() {
  for (int i = kGainCeilingMin; i <= kGainCeilingMax; i++) TEST_ASSERT_TRUE(int_in_range(i, kGainCeilingMin, kGainCeilingMax));
  TEST_ASSERT_FALSE(int_in_range(-1, 0, 6)); TEST_ASSERT_FALSE(int_in_range(7, 0, 6));
  TEST_ASSERT_FALSE(int_in_range(8, 0, 6)); TEST_ASSERT_FALSE(int_in_range(128, 0, 6));  // old multipliers
  TEST_ASSERT_FALSE(int_in_range(2.5, 0, 6)); TEST_ASSERT_FALSE(int_in_range(1e300, 0, 6));
  TEST_ASSERT_FALSE(int_in_range(-1e300, 0, 6)); TEST_ASSERT_FALSE(int_in_range(0.0 / 0.0, 0, 6));
  TEST_ASSERT_TRUE(int_in_range(4, 4, 63)); TEST_ASSERT_TRUE(int_in_range(63, 4, 63)); TEST_ASSERT_FALSE(int_in_range(64, 4, 63));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_double_reset_opens_portal);
  RUN_TEST(test_flag_cleared_after_5s);
  RUN_TEST(test_netlist_dedupes_and_caps_at_5);
  RUN_TEST(test_auth_accepts_bearer_or_query_only_when_equal);
  RUN_TEST(test_auth_rejects_length_mismatch_and_empty);
  RUN_TEST(test_int_in_range_checks_bounds_before_cast);
  return UNITY_END();
}
