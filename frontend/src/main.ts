import { createApp } from "vue";
import TrainSelector from "./components/TrainSelector.vue";

// Mount the uplift train-selector widget onto the placeholder rendered in the
// uplift request modal. The element is absent on pages without the modal, in
// which case the widget simply does not load.
const mountElement = document.querySelector<HTMLElement>(
  "#uplift-train-selector",
);

if (mountElement?.dataset.trainApiUrl) {
  createApp(TrainSelector, { apiUrl: mountElement.dataset.trainApiUrl }).mount(
    mountElement,
  );
}
