module.exports = {
  testEnvironment: "jsdom",
  setupFiles: ["./jest.setup.js"],
  testPathIgnorePatterns: ["/node_modules/", "/deps/", "/staticfiles/"],
  roots: ["<rootDir>/src/lando/static_src"],
};
