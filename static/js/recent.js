Vue.component('ManifestView', {
  props: ['item'],
  template: `
  <div class="column is-4">
    <div class="card manifest-view">
      <div class="card-content">
        <div class="media">
          <div class="media-left">
            <figure class="image manifest-preview">
              <a :href="viewerUrl" target="_blank">
                <img :src="item.preview" alt="Preview">
              </a>
            </figure>
          </div>
          <div class="media-content">
            <p class="title is-5 manifest-label">{{ truncatedLabel }}</p>
            <p class="subtitle is-6">
              <img class="attribution-logo" :src="item.attribution_logo">
              <span v-html="item.attribution" />
            </p>
          </div>
        </div>
      </div>
      <div class="card-footer">
        <a class="card-footer-item" :href="item.manifest">
          <img src="/static/img/iiif_128.png" alt="IIIF Manifest">
        </a>
        <a class="card-footer-item" :href="item.metsurl">
          <img src="/static/img/mets.png" alt="METS XML">
        </a>
        <a class="card-footer-item button is-primary" :href="viewerUrl"
           target="_blank">View</a>
      </div>
    </div>
  </div>`,
  computed: {
    viewerUrl: function() {
      return `/view/${this.item.id}`;
    },
    truncatedLabel: function() {
      if (this.item.label.length < 100) {
        return this.item.label;
      } else {
        var parts = this.item.label.split(" ");
        var label = "";
        while (label.length < 100) {
          var part = parts.shift();
          if ((label.length + part.length) > 100) {
            label += '…';
            break;
          }
          label += (" " + part);
        }
        return label;
      }
    }
  }
});

var app = new Vue({
  data: {
    nextPage: 1,
    items: [],
    isLoading: false
  },
  template: `
    <div class="container recent-manifests">
      <div class="columns is-multiline">
        <ManifestView v-for="item in items" :item="item" />
        <div v-if="nextPage" class="column is-half is-offset-3">
          <button @click="loadNext" class="button is-primary"
                  :class="{'is-loading': isLoading}">
            More
          </button>
        </div>
      </div>
    </div>`,
  methods: {
    loadNext: function() {
      var vm = this;
      axios.get('/api/recent', {params: {page: vm.nextPage}})
        .then(function(response) {
          vm.nextPage = response.data.next_page;
          vm.isLoading = false;
          response.data.manifests.forEach(function(m) {
            vm.items.push(m);
          }, this);
        });
      vm.isLoading = true;
    }
  },
  mounted: function() {
    this.loadNext();
  }
});

app.$mount(".recent");
